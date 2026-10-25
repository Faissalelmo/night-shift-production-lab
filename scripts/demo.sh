#!/usr/bin/env bash
# Run the five incident scenarios back to back, with pauses, for a screen recording.
# Use the fast schedule first (cp .env.demo.example .env && make up): about 15 min total.
#   DEMO_PAUSE=20 scripts/demo.sh
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

PAUSE=${DEMO_PAUSE:-15}
ORDER=(db_down disk_full slow_query duplicate_rerun missing_file)

pause() { note "(pause ${PAUSE}s — show Grafana / Kibana / the status page)"; sleep "$PAUSE"; }

say "Night shift production lab — demo"
note "Grafana http://localhost:${GRAFANA_PORT:-3000}  Kibana http://localhost:${KIBANA_PORT:-5601}"
note "Prometheus http://localhost:${PROMETHEUS_PORT:-9090}/alerts  Status http://localhost:${STATUS_PORT:-8088}"
"${DC[@]}" exec -T jobs python -m lab.tools.alerts list
pause

for s in "${ORDER[@]}"; do
    scripts/inject.sh "$s"
    pause
    scripts/recover.sh "$s"
    pause
done

say "All scenarios done"
"${DC[@]}" exec -T jobs python -m lab.tools.alerts list
