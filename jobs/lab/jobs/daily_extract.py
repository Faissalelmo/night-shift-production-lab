"""daily_extract — export new reconciliation mismatches to the outbox as CSV.

The file is written to a hidden .part file, fsync'ed and renamed, and the rows are
marked exported in the same database transaction. If the write fails (disk full),
the transaction rolls back: nothing is marked exported and the next successful run
picks the same rows up again. A file is produced on every run, even when empty, so
downstream consumers can tell "no mismatches" from "extract did not run".
"""

import contextlib
import csv
import os
import shutil
from datetime import datetime, timezone

from lab import config, metrics
from lab.db import connect
from lab.jsonlog import JsonLogger
from lab.runner import JobResult, run_job

JOB = "daily_extract"
HEADER = [
    "rrn",
    "status",
    "txn_amount",
    "settled_amount",
    "txn_value_date",
    "settled_value_date",
    "late_settlement",
    "detected_at",
]


def outbox_metrics() -> dict[str, float]:
    usage = shutil.disk_usage(config.OUTBOX_DIR)
    return {
        "extract_outbox_free_bytes": usage.free,
        "extract_outbox_used_ratio": usage.used / usage.total if usage.total else 0.0,
    }


def work(log: JsonLogger) -> JobResult:
    name = f"mismatches_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv"
    final = config.OUTBOX_DIR / name
    part = config.OUTBOX_DIR / f".{name}.part"

    try:
        rows = _export(name, final, part)
    except Exception:
        # Report free space even on failure: it is the first thing the disk_full
        # runbook asks for. Best effort — the original error is what matters.
        with contextlib.suppress(Exception):
            metrics.push(JOB, outbox_metrics())
        raise

    extra = outbox_metrics()
    log.info(
        f"extract written: {name}",
        file=name,
        rows_processed=len(rows),
        outbox_free_bytes=extra["extract_outbox_free_bytes"],
    )
    return JobResult(rows_processed=len(rows), did_work=True, extra_metrics=extra)


def _export(name: str, final, part) -> list:
    with connect() as conn, conn.transaction():
        rows = conn.execute(
            """SELECT id, rrn, status, txn_amount, settled_amount, txn_value_date,
                      settled_value_date, late_settlement, detected_at
               FROM reconciliation_results
               WHERE status <> 'MATCHED' AND exported_at IS NULL
               ORDER BY id
               FOR UPDATE"""
        ).fetchall()

        try:
            with part.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(HEADER)
                writer.writerows(r[1:] for r in rows)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(part, final)
        except OSError:
            part.unlink(missing_ok=True)
            raise

        if rows:
            conn.execute(
                "UPDATE reconciliation_results SET exported_at = now(), export_file = %s WHERE id = ANY(%s)",
                (name, [r[0] for r in rows]),
            )
    return rows


def main() -> None:
    run_job(JOB, work)


if __name__ == "__main__":
    main()
