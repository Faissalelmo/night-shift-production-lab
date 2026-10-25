#!/usr/bin/env bash
# Fix what inject.sh broke.   scripts/recover.sh <scenario> [--no-wait]
# Re-runs the affected jobs immediately (as an operator would, rather than waiting
# for cron), then by default waits until the alerts have cleared.
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

SCENARIO=${1:-}
valid_scenario "$SCENARIO" || usage_scenario
WAIT=1
[[ "${2:-}" == "--no-wait" ]] && WAIT=0
EXPECT=()

recover_missing_file() {
    say "missing_file — restart the generator, then load the backlog"
    "${DC[@]}" start generator
    note "waiting for a new settlement file in ./inbox ..."
    for _ in $(seq 1 30); do
        "${DC[@]}" exec -T jobs sh -c 'ls /data/inbox/*.csv >/dev/null 2>&1' && break
        sleep 2
    done
    run_job import_settlement_file
    run_synthetic
    EXPECT=("BatchJobSilentStop - 120" "SyntheticCheckFailed - 120")
}

recover_db_down() {
    say "db_down — start PostgreSQL and catch up"
    "${DC[@]}" start postgres
    note "waiting for PostgreSQL to accept connections ..."
    until "${DC[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do sleep 2; done
    run_job import_settlement_file
    run_job reconcile_transactions
    run_job daily_extract
    run_synthetic
    EXPECT=("BatchJobFailed - 120" "PostgresDown - 120" "SyntheticCheckFailed - 120")
}

recover_disk_full() {
    say "disk_full — free the outbox and re-run the extract"
    "${DC[@]}" exec -T jobs sh -c 'rm -f /data/outbox/.ballast; df -h /data/outbox | tail -n 1' \
        | while read -r line; do note "df: $line"; done
    run_job daily_extract
    run_synthetic
    EXPECT=("BatchJobFailed - 120" "OutboxAlmostFull - 120" "SyntheticCheckFailed - 120")
}

recover_slow_query() {
    say "slow_query — remove the injected delay"
    clear_fault slow_query
    note "waiting for the slow run to finish, then re-running reconciliation:"
    run_job reconcile_transactions
    EXPECT=("BatchJobTooSlow - 120")
}

recover_duplicate_rerun() {
    say "duplicate_rerun — nothing to repair, verify and file the evidence"
    note "rejected copies (kept for the audit trail):"
    "${DC[@]}" exec -T jobs sh -c 'ls -1 /data/archive/rejected/ 2>/dev/null | tail -n 4' \
        | while read -r line; do note "  $line"; done
    psql_q "SELECT count(*) AS settlement_rows, count(DISTINCT rrn) AS distinct_rrn,
                   count(*) - count(DISTINCT rrn) AS duplicates FROM settlement_rows;"
}

recover_mismatch_spike() {
    say "mismatch_spike — after escalation, the next reconciliation is back to normal"
    run_job reconcile_transactions
    note "The alert is an event: it clears by itself 5 min after the spike."
    EXPECT=("ReconciliationMismatchesHigh - 420")
}

recover_slow_page() {
    say "slow_page — remove the delay and re-check"
    clear_fault slow_page
    run_synthetic
    EXPECT=("SyntheticCheckSlow - 120")
}

"recover_${SCENARIO}"

if [[ $WAIT -eq 1 && ${#EXPECT[@]} -gt 0 ]]; then
    say "Waiting for the alerts to clear"
    wait_expected inactive
    ok "recovered — alerts cleared"
fi
