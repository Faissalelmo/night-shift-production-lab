"""Common wrapper for every batch job.

A job is a function `work(log) -> JobResult`. The runner adds what production jobs
need around it: a run_id, a lock against overlapping runs, timing, a classified
error_type, a row in job_runs, Pushgateway metrics, and a non-zero exit on failure.
"""

import errno
import fcntl
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import psycopg

from lab import config, metrics
from lab.db import connect
from lab.jsonlog import JsonLogger


class JobError(Exception):
    """Expected, classified failure (bad input file, ...)."""

    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


@dataclass
class JobResult:
    rows_processed: int = 0
    # False when the run was healthy but had nothing to do (no file received).
    # Such a run does not refresh last_success_timestamp.
    did_work: bool = True
    extra_metrics: dict[str, float] = field(default_factory=dict)


def classify(exc: BaseException) -> str:
    if isinstance(exc, JobError):
        return exc.error_type
    if isinstance(exc, psycopg.errors.QueryCanceled):  # subclass of OperationalError
        return "db_timeout"
    if isinstance(exc, psycopg.OperationalError):
        return "db_connection"
    if isinstance(exc, psycopg.Error):
        return "db_error"
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "disk_full"
    if isinstance(exc, OSError):
        return "io_error"
    return "unexpected"


def _record_run(run_id, job, started, finished, ok, result, error_type, message, log):
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO job_runs (run_id, job, started_at, finished_at, status, did_work,
                                         rows_processed, error_type, message)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (run_id) DO NOTHING""",
                (
                    run_id,
                    job,
                    started,
                    finished,
                    "success" if ok else "failed",
                    result.did_work,
                    result.rows_processed,
                    error_type,
                    message[:500],
                ),
            )
    except psycopg.Error as exc:
        # Expected while the database itself is the incident.
        log.warning("could not record run in job_runs", error_type="db_connection", detail=str(exc))


def _push(job, values, log):
    try:
        metrics.push(job, values)
    except Exception as exc:  # noqa: BLE001 - monitoring outage must not fail the job
        log.warning("could not push metrics", error_type="pushgateway_unreachable", detail=str(exc))


def run_job(job: str, work: Callable[[JsonLogger], JobResult]) -> None:
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    log = JsonLogger(job, run_id)

    # One run at a time. Cron runs give up if the previous run is still going;
    # manual runs (LAB_LOCK_WAIT=1, used by the recover scripts) wait for it.
    lock = open(f"/tmp/{job}.lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        flags = fcntl.LOCK_EX if os.environ.get("LAB_LOCK_WAIT") == "1" else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(lock, flags)
    except BlockingIOError:
        log.warning("previous run still in progress, skipping this run", error_type="overlapping_run")
        sys.exit(0)

    interval = config.SCHEDULE_MINUTES[job] * 60
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    log.info("run started")
    _push(
        job,
        {
            "batch_job_running": 1,
            "batch_job_last_start_timestamp_seconds": started.timestamp(),
            "batch_job_schedule_interval_seconds": interval,
        },
        log,
    )

    result, error_type, message, ok = JobResult(did_work=False), None, "", True
    try:
        result = work(log)
    except Exception as exc:  # noqa: BLE001 - every failure is classified and reported
        ok, error_type, message = False, classify(exc), f"{type(exc).__name__}: {exc}".strip()

    duration = time.monotonic() - t0
    finished = datetime.now(timezone.utc)
    _record_run(run_id, job, started, finished, ok, result, error_type, message, log)

    values = {
        "batch_job_running": 0,
        "batch_job_last_run_timestamp_seconds": finished.timestamp(),
        "batch_job_last_run_duration_seconds": duration,
        "batch_job_rows_processed": result.rows_processed,
        "batch_job_last_run_status": 1 if ok else 0,
        "batch_job_schedule_interval_seconds": interval,
        **result.extra_metrics,
    }
    if ok and result.did_work:
        values["batch_job_last_success_timestamp_seconds"] = finished.timestamp()
    _push(job, values, log)

    fields = {"rows_processed": result.rows_processed, "duration_ms": round(duration * 1000)}
    if ok:
        log.info("run finished", **fields)
        sys.exit(0)
    log.error(f"run failed: {message}", error_type=error_type, **fields)
    sys.exit(1)
