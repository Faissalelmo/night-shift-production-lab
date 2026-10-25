#!/usr/bin/env bash
# Wait until every service is running/healthy and the Kibana import has finished.
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

TIMEOUT=${1:-420}
deadline=$(( $(date +%s) + TIMEOUT ))
say "Waiting for the lab to be healthy (up to ${TIMEOUT}s)"

while :; do
    pending=()
    while IFS='|' read -r service state health exit_code; do
        if [[ $service == kibana-setup ]]; then
            [[ $state == exited && $exit_code == 0 ]] || pending+=("$service:$state")
        elif [[ $state != running ]]; then
            pending+=("$service:$state")
        elif [[ -n $health && $health != healthy ]]; then
            pending+=("$service:$health")
        fi
    # "|" as separator: Health is empty for services without a healthcheck.
    done < <("${DC[@]}" ps -a --format '{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}' | tr -d '\r')

    if [[ ${#pending[@]} -eq 0 ]]; then
        ok "all services healthy"
        "${DC[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
        exit 0
    fi
    if (( $(date +%s) > deadline )); then
        warn "still waiting on: ${pending[*]}"
        exit 1
    fi
    printf '  waiting on: %s\r' "${pending[*]}"
    sleep 5
done
