"""import_settlement_file — load settlement CSVs dropped in the inbox.

Idempotent on two levels:
  * a file whose name or SHA-256 was already loaded is skipped with a WARNING
    (error_type=duplicate_file) and moved to archive/rejected/;
  * rows are inserted with ON CONFLICT (rrn) DO NOTHING, so even a crash between
    the commit and the move to archive cannot create duplicate rows.

An empty inbox is not a failure, but it is not a success either: the run ends with
did_work=False, so last_success_timestamp stops moving and the "silent stop"
alert fires if no file arrives for 3 schedule intervals.
"""

import csv
import hashlib
import io
import shutil
from pathlib import Path

from lab import config
from lab.db import connect
from lab.jsonlog import JsonLogger
from lab.runner import JobError, JobResult, run_job

JOB = "import_settlement_file"
COLUMNS = ["rrn", "amount", "currency", "value_date", "institution_code"]


def _move(src: Path, dest_dir: Path, suffix: str = "") -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{src.name}{suffix}"
    n = 1
    while dest.exists():
        dest = dest_dir / f"{src.name}{suffix}.{n}"
        n += 1
    # shutil.move, not rename: inbox and archive are separate mounts.
    shutil.move(str(src), str(dest))
    return dest


def _parse(path: Path, raw: bytes) -> list[tuple]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    if reader.fieldnames != COLUMNS:
        raise JobError("bad_file_format", f"{path.name}: expected header {COLUMNS}, got {reader.fieldnames}")
    rows = []
    for line_no, row in enumerate(reader, start=2):
        if len(row["rrn"]) != 12 or not row["rrn"].isdigit():
            raise JobError("bad_file_format", f"{path.name}:{line_no}: invalid RRN {row['rrn']!r}")
        rows.append(tuple(row[c] for c in COLUMNS))
    return rows


def work(log: JsonLogger) -> JobResult:
    loaded_files = total_rows = 0
    # Connect before looking at the inbox: with the database down the job must fail
    # (db_connection), even on a run that would have found no file.
    with connect() as conn:
        files = sorted(config.INBOX_DIR.glob("*.csv"))
        if not files:
            log.warning("no settlement file in inbox, nothing to load", error_type="no_input_file")
            return JobResult(rows_processed=0, did_work=False)

        for path in files:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()

            already = conn.execute(
                "SELECT file_name, loaded_at FROM settlement_files WHERE sha256 = %s OR file_name = %s",
                (digest, path.name),
            ).fetchone()
            if already:
                dest = _move(path, config.REJECTED_DIR, ".duplicate")
                log.warning(
                    f"duplicate settlement file skipped: {path.name} was already loaded "
                    f"as {already[0]} at {already[1]:%Y-%m-%d %H:%M:%S}",
                    error_type="duplicate_file",
                    file=path.name,
                    moved_to=str(dest),
                    rows_processed=0,
                )
                continue

            try:
                rows = _parse(path, raw)
            except JobError:
                _move(path, config.REJECTED_DIR, ".bad_format")
                raise

            with conn.transaction():
                file_id = conn.execute(
                    "INSERT INTO settlement_files (file_name, sha256, run_id) VALUES (%s, %s, %s) RETURNING id",
                    (path.name, digest, log.run_id),
                ).fetchone()[0]
                conn.execute(
                    "CREATE TEMP TABLE incoming (rrn CHAR(12), amount NUMERIC(14,2), currency CHAR(3),"
                    " value_date DATE, institution_code TEXT) ON COMMIT DROP"
                )
                with conn.cursor().copy(
                    "COPY incoming (rrn, amount, currency, value_date, institution_code) FROM STDIN"
                ) as copy:
                    for row in rows:
                        copy.write_row(row)
                inserted = conn.execute(
                    """INSERT INTO settlement_rows (file_id, rrn, amount, currency, value_date, institution_code)
                       SELECT %s, rrn, amount, currency, value_date, institution_code FROM incoming
                       ON CONFLICT (rrn) DO NOTHING""",
                    (file_id,),
                ).rowcount
                conn.execute("UPDATE settlement_files SET row_count = %s WHERE id = %s", (inserted, file_id))

            _move(path, config.ARCHIVE_DIR)
            loaded_files += 1
            total_rows += inserted
            skipped = len(rows) - inserted
            log.info(
                f"settlement file loaded: {path.name}",
                file=path.name,
                rows_in_file=len(rows),
                rows_processed=inserted,
                rows_skipped_existing=skipped,
            )

    return JobResult(rows_processed=total_rows, did_work=loaded_files > 0)


def main() -> None:
    run_job(JOB, work)


if __name__ == "__main__":
    main()
