"""Seed two days of synthetic history the first time the lab starts.

Safe to run on every container start: it does nothing once transactions exist.
"""

import hashlib
import random
import time
from datetime import datetime, timedelta, timezone

import psycopg

from lab import fakedata
from lab.db import connect
from lab.jobs.reconcile_transactions import MATCH_SETTLED, MISSING
from lab.jsonlog import JsonLogger

TXNS_PER_DAY = 1200


def wait_for_db(log: JsonLogger, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with connect():
                return
        except psycopg.OperationalError as exc:
            if time.monotonic() > deadline:
                raise
            log.warning(f"database not ready yet: {exc}", error_type="db_connection")
            time.sleep(3)


def main() -> None:
    log = JsonLogger("seed", "seed")
    wait_for_db(log)
    random.seed(20260801)  # same history on every fresh install

    with connect() as conn, conn.transaction():
        if conn.execute("SELECT EXISTS (SELECT 1 FROM transactions)").fetchone()[0]:
            log.info("database already seeded, skipping")
            return

        now = datetime.now(timezone.utc)
        total = 0
        for days_ago in (2, 1):
            day = (now - timedelta(days=days_ago)).date()
            txns = [fakedata.transaction(day) for _ in range(TXNS_PER_DAY)]
            with conn.cursor().copy(
                "COPY transactions (rrn, amount, currency, value_date, channel, institution_code, created_at)"
                " FROM STDIN"
            ) as copy:
                for t in txns:
                    created = datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(
                        seconds=random.randint(0, 86399)
                    )
                    copy.write_row(
                        (
                            t["rrn"],
                            t["amount"],
                            t["currency"],
                            t["value_date"],
                            t["channel"],
                            t["institution_code"],
                            created,
                        )
                    )

            name = f"SETTLEMENT_{day:%Y%m%d}_SEED.csv"
            rows = fakedata.settlement_rows(txns)
            file_id = conn.execute(
                "INSERT INTO settlement_files (file_name, sha256, row_count, run_id) VALUES (%s, %s, %s, 'seed')"
                " RETURNING id",
                (name, hashlib.sha256(name.encode()).hexdigest(), len(rows)),
            ).fetchone()[0]
            with conn.cursor().copy(
                "COPY settlement_rows (file_id, rrn, amount, currency, value_date, institution_code) FROM STDIN"
            ) as copy:
                for r in rows:
                    copy.write_row(
                        (file_id, r["rrn"], r["amount"], r["currency"], r["value_date"], r["institution_code"])
                    )
            total += len(txns)

        # Reconcile the history here and mark its breaks as already exported, so the first
        # live reconciliation only sees live data (and doesn't open the lab with a
        # ReconciliationMismatchesHigh alert about two days of seed data).
        params = {"run_id": "seed", "grace": 0}
        conn.execute(MATCH_SETTLED, params)
        conn.execute(MISSING, params)
        conn.execute(
            "UPDATE reconciliation_results SET exported_at = now(), export_file = 'seed-history'"
            " WHERE run_id = 'seed' AND status <> 'MATCHED'"
        )

    log.info(f"seeded {total} historical transactions", rows_processed=total)


if __name__ == "__main__":
    main()
