"""Upstream simulator: books new transactions and drops the matching settlement CSV
into the inbox every GENERATOR_EVERY_SECONDS.

    python -m lab.generator            run forever (the `generator` service)
    python -m lab.generator --once     one cycle
    python -m lab.generator --burst N  one file of N transactions whose settlement
                                       amounts are all wrong (mismatch_spike scenario)
"""

import argparse
import csv
import os
import random
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from lab import config, fakedata, metrics
from lab.db import connect
from lab.jsonlog import JsonLogger
from lab.runner import classify

JOB = "settlement_generator"
CSV_COLUMNS = ["rrn", "amount", "currency", "value_date", "institution_code"]


def book_transactions(n: int) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    candidates = [fakedata.transaction(today) for _ in range(n)]
    booked = []
    with connect() as conn, conn.transaction():
        for t in candidates:
            row = conn.execute(
                """INSERT INTO transactions (rrn, amount, currency, value_date, channel, institution_code)
                   VALUES (%(rrn)s, %(amount)s, %(currency)s, %(value_date)s, %(channel)s, %(institution_code)s)
                   ON CONFLICT (rrn) DO NOTHING RETURNING rrn""",
                t,
            ).fetchone()
            if row:
                booked.append(t)
    return booked


def write_settlement_file(rows: list[dict], tag: str = "") -> str:
    stamp = datetime.now(timezone.utc)
    name = f"SETTLEMENT_{stamp:%Y%m%d_%H%M%S}{tag}_{uuid.uuid4().hex[:4]}.csv"
    part = config.INBOX_DIR / f".{name}.part"
    with part.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    # Atomic within the inbox: the importer only ever sees complete *.csv files.
    os.replace(part, config.INBOX_DIR / name)
    return name


def cycle(log: JsonLogger, size: int, burst: bool = False) -> None:
    txns = book_transactions(size)
    if burst:
        rows = fakedata.settlement_rows(txns, anomalies=False)
        for r in rows:
            r["amount"] = r["amount"] + Decimal(random.randint(100, 9999)) / 100
    else:
        rows = fakedata.settlement_rows(txns)
    name = write_settlement_file(rows, "_BURST" if burst else "")
    log.info(f"settlement file dropped: {name}", file=name, transactions_booked=len(txns), rows_processed=len(rows))
    try:
        metrics.push(JOB, {"generator_last_file_timestamp_seconds": time.time(), "generator_rows_last_file": len(rows)})
    except Exception as exc:  # noqa: BLE001
        log.warning("could not push metrics", error_type="pushgateway_unreachable", detail=str(exc))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--burst", type=int, default=0)
    args = parser.parse_args()

    log = JsonLogger(JOB)
    if args.burst:
        log.run_id = f"burst-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
        cycle(log, args.burst, burst=True)
        return
    while True:
        log.run_id = f"gen-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
        try:
            cycle(log, config.GENERATOR_BATCH_SIZE)
        except Exception as exc:  # noqa: BLE001 - keep producing once the incident is over
            log.error(f"generator cycle failed: {exc}", error_type=classify(exc))
        if args.once:
            return
        time.sleep(config.GENERATOR_EVERY_SECONDS)


if __name__ == "__main__":
    main()
