#!/usr/bin/env bash
# Break the lab on purpose.   scripts/inject.sh <scenario> [--no-wait]
# By default waits until the expected alerts fire (Prometheus and Grafana).
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

SCENARIO=${1:-}
valid_scenario "$SCENARIO" || usage_scenario
WAIT=1
[[ "${2:-}" == "--no-wait" ]] && WAIT=0
EXPECT=()

inject_missing_file() {
    say "missing_file — the upstream stops sending settlement files"
    "${DC[@]}" stop generator
    local timeout=$(( (IMPORT_EVERY_MIN * 5 + 2) * 60 ))
    note "import_settlement_file keeps running every ${IMPORT_EVERY_MIN} min, finds an empty inbox,"
    note "logs WARNING error_type=no_input_file and stops refreshing last_success_timestamp."
    note "Nothing fails — only the 'no success in 3× the interval' rule can catch this."
    EXPECT=("BatchJobSilentStop import_settlement_file $timeout")
}

inject_db_down() {
    say "db_down — PostgreSQL stops"
    "${DC[@]}" stop postgres
    note "running import_settlement_file now instead of waiting for cron:"
    run_job import_settlement_file || true
    run_synthetic
    EXPECT=("BatchJobFailed import_settlement_file 180" "PostgresDown - 180" "SyntheticCheckFailed - 180")
}

inject_disk_full() {
    say "disk_full — the 5 MB outbox volume fills up"
    "${DC[@]}" exec -T jobs sh -c \
        'dd if=/dev/zero of=/data/outbox/.ballast bs=64k 2>/dev/null; df -h /data/outbox | tail -n 1' \
        | while read -r line; do note "df: $line"; done
    note "running daily_extract now:"
    run_job daily_extract || true
    EXPECT=("BatchJobFailed daily_extract 180" "OutboxAlmostFull daily_extract 180")
}

inject_slow_query() {
    say "slow_query — reconciliation query degrades (pg_sleep 120 s injected)"
    set_fault slow_query 120
    "${DC[@]}" exec -d -e LAB_LOCK_WAIT=1 jobs run-job reconcile_transactions
    note "reconcile_transactions started in the background; it will run ~2 min."
    note "Cron runs that start meanwhile skip with WARNING error_type=overlapping_run."
    EXPECT=("BatchJobTooSlow reconcile_transactions 150")
}

inject_duplicate_rerun() {
    say "duplicate_rerun — an already-processed settlement file is dropped again"
    local name
    # shellcheck disable=SC2016  # $f expands inside the container, on purpose
    name=$("${DC[@]}" exec -T jobs sh -c \
        'f=$(ls -t /data/archive/*.csv | head -n 1); cp "$f" /data/inbox/;
         cp "$f" "/data/inbox/RESENT_$(basename "$f")"; basename "$f"' | tr -d '\r')
    note "re-dropped $name twice: same name, and renamed RESENT_$name (same content)"
    note "rows loaded from that file before the re-run:"
    psql_q "SELECT f.file_name, count(r.id) AS rows_in_db FROM settlement_files f
            JOIN settlement_rows r ON r.file_id = f.id WHERE f.file_name = '$name' GROUP BY 1;"
    run_job import_settlement_file
    note "warnings logged by the run:"
    "${DC[@]}" exec -T jobs sh -c 'grep "\"duplicate_file\"" /var/log/lab/import_settlement_file.log | tail -n 2' \
        | cut -c1-240 | while read -r line; do note "$line"; done
    note "proof of idempotency — same row count for that file, and no RRN appears twice:"
    psql_q "SELECT f.file_name, count(r.id) AS rows_in_db FROM settlement_files f
            JOIN settlement_rows r ON r.file_id = f.id WHERE f.file_name = '$name' GROUP BY 1;"
    psql_q "SELECT count(*) AS settlement_rows, count(DISTINCT rrn) AS distinct_rrn,
                   count(*) - count(DISTINCT rrn) AS duplicates FROM settlement_rows;"
    note "No alert is expected: a duplicate is a WARNING (Kibana: error_type : duplicate_file)."
}

inject_mismatch_spike() {
    say "mismatch_spike (bonus) — a settlement file arrives with 120 wrong amounts"
    "${DC[@]}" exec -T jobs python -m lab.generator --burst 120 | tail -n 1 | cut -c1-200
    run_job import_settlement_file
    run_job reconcile_transactions
    EXPECT=("ReconciliationMismatchesHigh reconcile_transactions 120")
}

inject_slow_page() {
    say "slow_page (bonus) — the status page answers in 4 s"
    set_fault slow_page 4
    run_synthetic
    EXPECT=("SyntheticCheckSlow synthetic_status_check 120")
}

"inject_${SCENARIO}"

if [[ $WAIT -eq 1 && ${#EXPECT[@]} -gt 0 ]]; then
    say "Waiting for the expected alerts to fire"
    wait_expected firing
    ok "incident detected — follow runbooks/, then: scripts/recover.sh $SCENARIO"
fi
