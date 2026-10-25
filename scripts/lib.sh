#!/usr/bin/env bash
# Shared helpers, sourced by the other scripts. Needs only docker + bash.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: don't rewrite /data/... into C:/...

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi
POSTGRES_USER=${POSTGRES_USER:-lab}
POSTGRES_DB=${POSTGRES_DB:-payments}
IMPORT_EVERY_MIN=${IMPORT_EVERY_MIN:-5}
RECONCILE_EVERY_MIN=${RECONCILE_EVERY_MIN:-10}
EXTRACT_EVERY_MIN=${EXTRACT_EVERY_MIN:-15}

DC=(docker compose)
SCENARIOS=(missing_file db_down disk_full slow_query duplicate_rerun mismatch_spike slow_page)

say()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✔ %s\033[0m\n' "$*"; }
warn() { printf '  \033[33m! %s\033[0m\n' "$*"; }

usage_scenario() {
    echo "usage: $0 <scenario> [--no-wait]" >&2
    echo "scenarios: ${SCENARIOS[*]}" >&2
    exit 2
}

valid_scenario() {
    local s
    for s in "${SCENARIOS[@]}"; do [[ "$s" == "${1:-}" ]] && return 0; done
    return 1
}

psql_q() {
    "${DC[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "$1"
}

set_fault()   { psql_q "INSERT INTO lab_faults (name, value) VALUES ('$1', $2)
                        ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value, set_at = now();" >/dev/null; }
clear_fault() { psql_q "DELETE FROM lab_faults WHERE name = '$1';" >/dev/null; }

# Run a batch job now (waits for a run already in progress), print its last log line.
# Returns the job's exit code.
run_job() {
    local out rc=0
    out=$("${DC[@]}" exec -T -e LAB_LOCK_WAIT=1 jobs run-job "$1" 2>&1) || rc=$?
    note "$1 → exit $rc: $(printf '%s\n' "$out" | tail -n 1 | cut -c1-220)"
    return "$rc"
}

run_synthetic() {
    local out
    out=$("${DC[@]}" exec -T synthetic python check.py --once 2>&1 | tail -n 1) || true
    note "synthetic check → $(printf '%s' "$out" | cut -c1-200)"
}

# wait_alert <alertname> <firing|inactive> [job|-] [timeout_s]
# Checks Prometheus and Grafana alerting; "-" means "any job".
wait_alert() {
    local args=(wait "$1" "$2" --timeout "${4:-300}")
    if [[ -n "${3:-}" && "${3:-}" != "-" ]]; then args+=(--job "$3"); fi
    "${DC[@]}" exec -T jobs python -m lab.tools.alerts "${args[@]}"
}

# EXPECT holds "alertname job timeout" triples set by a scenario; wait for all.
wait_expected() {
    local state=$1 failed=0 entry name job timeout
    for entry in "${EXPECT[@]}"; do
        read -r name job timeout <<<"$entry"
        note "waiting for $name${job:+ (job=$job)} to be $state (up to ${timeout}s)"
        wait_alert "$name" "$state" "$job" "$timeout" || failed=1
    done
    return "$failed"
}
