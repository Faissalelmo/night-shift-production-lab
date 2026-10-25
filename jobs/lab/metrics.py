"""Push metrics to the Prometheus Pushgateway.

pushadd (HTTP POST) only replaces the metric names it sends, so a run that does not
send batch_job_last_success_timestamp_seconds leaves the previous value in place.
That is what makes the "no success in 3x the interval" alert work.
"""

from prometheus_client import CollectorRegistry, Gauge, pushadd_to_gateway

from lab import config

HELP = {
    "batch_job_running": "1 while the job is running, 0 otherwise",
    "batch_job_last_start_timestamp_seconds": "Unix time the last run started",
    "batch_job_last_run_timestamp_seconds": "Unix time the last run finished",
    "batch_job_last_success_timestamp_seconds": "Unix time of the last run that succeeded and did work",
    "batch_job_last_run_duration_seconds": "Duration of the last run",
    "batch_job_rows_processed": "Rows processed by the last run",
    "batch_job_last_run_status": "1 if the last run succeeded, 0 if it failed",
    "batch_job_schedule_interval_seconds": "Configured schedule interval of the job",
}


def push(job: str, values: dict[str, float]) -> None:
    registry = CollectorRegistry()
    for name, value in values.items():
        Gauge(name, HELP.get(name, name), registry=registry).set(value)
    pushadd_to_gateway(config.PUSHGATEWAY_URL, job=job, registry=registry, timeout=5)
