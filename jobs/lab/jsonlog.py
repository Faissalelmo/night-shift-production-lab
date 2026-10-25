"""Structured JSON logging: one JSON object per line, to stdout and to a per-job file
that Filebeat ships to Elasticsearch.

Every line carries the same core fields so Kibana sees a stable schema:
timestamp, job, run_id, level, message, rows_processed, duration_ms, error_type.
"""

import json
import sys
from datetime import datetime, timezone

from lab import config


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonLogger:
    def __init__(self, job: str, run_id: str | None = None):
        self.job = job
        self.run_id = run_id
        self._path = config.LOG_DIR / f"{job}.log"

    def log(self, level: str, message: str, **fields) -> None:
        record = {
            "timestamp": utc_now_iso(),
            "job": self.job,
            "run_id": self.run_id,
            "level": level,
            "message": message,
            "rows_processed": fields.pop("rows_processed", None),
            "duration_ms": fields.pop("duration_ms", None),
            "error_type": fields.pop("error_type", None),
            **fields,
        }
        line = json.dumps(record, default=str)
        print(line, flush=True)
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:  # logging must never take the job down
            print(
                json.dumps({"level": "WARNING", "message": f"cannot write log file: {exc}"}),
                file=sys.stderr,
                flush=True,
            )

    def info(self, message: str, **fields) -> None:
        self.log("INFO", message, **fields)

    def warning(self, message: str, **fields) -> None:
        self.log("WARNING", message, **fields)

    def error(self, message: str, **fields) -> None:
        self.log("ERROR", message, **fields)
