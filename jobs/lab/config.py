"""Runtime configuration, all from environment variables (see .env.example)."""

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://lab:lab@postgres:5432/payments")
PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "pushgateway:9091")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")

INBOX_DIR = Path(os.environ.get("INBOX_DIR", "/data/inbox"))
ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_DIR", "/data/archive"))
REJECTED_DIR = ARCHIVE_DIR / "rejected"
OUTBOX_DIR = Path(os.environ.get("OUTBOX_DIR", "/data/outbox"))
LOG_DIR = Path(os.environ.get("LOG_DIR", "/var/log/lab"))

# Schedule of each batch job, in minutes. The crontab is generated from the same
# values (jobs/entrypoint.sh), and each job publishes its interval so the
# "silent stop" alert can be written once for every job.
SCHEDULE_MINUTES = {
    "import_settlement_file": _int("IMPORT_EVERY_MIN", 5),
    "reconcile_transactions": _int("RECONCILE_EVERY_MIN", 10),
    "daily_extract": _int("EXTRACT_EVERY_MIN", 15),
}

# A transaction without a settlement row is only flagged once it is this old.
RECON_GRACE_MINUTES = _int("RECON_GRACE_MINUTES", 30)

GENERATOR_EVERY_SECONDS = _int("GENERATOR_EVERY_SECONDS", 120)
GENERATOR_BATCH_SIZE = _int("GENERATOR_BATCH_SIZE", 40)
