#!/usr/bin/env bash
# End-to-end check: for each scenario, inject → expected alerts fire → recover →
# alerts clear. Exit code 0 only if every step passed.
#   scripts/verify.sh                 all scenarios
#   scripts/verify.sh db_down disk_full
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

if [[ $# -gt 0 ]]; then TODO=("$@"); else TODO=("${SCENARIOS[@]}"); fi
RESULTS=()   # indexed, not associative: macOS still ships bash 3.2

for s in "${TODO[@]}"; do
    valid_scenario "$s" || usage_scenario
    start=$(date +%s)
    if scripts/inject.sh "$s" && scripts/recover.sh "$s"; then
        RESULTS+=("PASS ($(( $(date +%s) - start ))s)")
    else
        RESULTS+=("FAIL")
    fi
done

say "Summary"
rc=0
for i in "${!TODO[@]}"; do
    printf '  %-16s %s\n' "${TODO[$i]}" "${RESULTS[$i]}"
    [[ ${RESULTS[$i]} == FAIL ]] && rc=1
done
exit "$rc"
