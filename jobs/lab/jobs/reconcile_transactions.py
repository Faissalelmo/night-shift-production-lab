"""reconcile_transactions — match transactions against settlement rows.

Matching key: RRN, then amount and value date. One verdict per RRN
(reconciliation_results.rrn is UNIQUE, inserts use ON CONFLICT DO NOTHING), so
re-running never duplicates a result.

  MATCHED                 settlement row agrees with the transaction
  AMOUNT_MISMATCH         same RRN, different amount
  DATE_MISMATCH           same RRN and amount, different value date
  UNKNOWN_RRN             settled, but no such transaction on our side
  MISSING_IN_SETTLEMENT   transaction older than the grace period, never settled

A settlement row that arrives after its transaction was flagged
MISSING_IN_SETTLEMENT re-qualifies that result (late_settlement = true).
"""

from lab import config
from lab.db import connect, fault
from lab.jsonlog import JsonLogger
from lab.runner import JobResult, run_job

JOB = "reconcile_transactions"

VERDICT = """CASE WHEN t.rrn IS NULL          THEN 'UNKNOWN_RRN'
                  WHEN t.amount <> s.amount    THEN 'AMOUNT_MISMATCH'
                  WHEN t.value_date <> s.value_date THEN 'DATE_MISMATCH'
                  ELSE 'MATCHED' END"""

MATCH_SETTLED = f"""
WITH new AS (
    INSERT INTO reconciliation_results
        (rrn, status, txn_amount, settled_amount, txn_value_date, settled_value_date, run_id)
    SELECT s.rrn, {VERDICT}, t.amount, s.amount, t.value_date, s.value_date, %(run_id)s
    FROM settlement_rows s
    LEFT JOIN transactions t ON t.rrn = s.rrn
    WHERE NOT EXISTS (SELECT 1 FROM reconciliation_results r WHERE r.rrn = s.rrn)
    ON CONFLICT (rrn) DO NOTHING
    RETURNING status)
SELECT status, count(*) FROM new GROUP BY status"""

LATE_SETTLEMENT = f"""
WITH upd AS (
    UPDATE reconciliation_results r
    SET status = {VERDICT}, settled_amount = s.amount, settled_value_date = s.value_date,
        late_settlement = true, run_id = %(run_id)s, detected_at = now(),
        exported_at = NULL, export_file = NULL
    FROM settlement_rows s JOIN transactions t ON t.rrn = s.rrn
    WHERE r.rrn = s.rrn AND r.status = 'MISSING_IN_SETTLEMENT'
    RETURNING r.status)
SELECT status, count(*) FROM upd GROUP BY status"""

MISSING = """
WITH new AS (
    INSERT INTO reconciliation_results (rrn, status, txn_amount, txn_value_date, run_id)
    SELECT t.rrn, 'MISSING_IN_SETTLEMENT', t.amount, t.value_date, %(run_id)s
    FROM transactions t
    WHERE t.created_at < now() - make_interval(mins => %(grace)s)
      AND NOT EXISTS (SELECT 1 FROM settlement_rows s WHERE s.rrn = t.rrn)
      AND NOT EXISTS (SELECT 1 FROM reconciliation_results r WHERE r.rrn = t.rrn)
    ON CONFLICT (rrn) DO NOTHING
    RETURNING status)
SELECT status, count(*) FROM new GROUP BY status"""


def work(log: JsonLogger) -> JobResult:
    counts: dict[str, int] = {}
    params = {"run_id": log.run_id, "grace": config.RECON_GRACE_MINUTES}

    with connect() as conn, conn.transaction():
        delay = fault(conn, "slow_query")
        if delay:
            # Fault injection (scripts/inject.sh slow_query): simulates a query that
            # suddenly degrades, e.g. after a lost index or a lock wait.
            conn.execute("SELECT pg_sleep(%s)", (delay,))

        for sql in (MATCH_SETTLED, LATE_SETTLEMENT, MISSING):
            for status, n in conn.execute(sql, params).fetchall():
                counts[status] = counts.get(status, 0) + n

    processed = sum(counts.values())
    mismatches = processed - counts.get("MATCHED", 0)
    log.info(
        f"reconciliation done: {processed} verdicts, {mismatches} mismatches",
        rows_processed=processed,
        mismatches=mismatches,
        by_status=counts,
    )
    return JobResult(
        rows_processed=processed,
        did_work=True,
        extra_metrics={"reconciliation_mismatches_last_run": mismatches},
    )


def main() -> None:
    run_job(JOB, work)


if __name__ == "__main__":
    main()
