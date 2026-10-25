#!/bin/sh
# One-shot: wait for Kibana, import saved-objects.ndjson, make "Job logs" the default
# data view. Run by the kibana-setup service; safe to re-run (overwrite=true).
set -eu
KIBANA="${KIBANA_URL:-http://kibana:5601}"

echo "waiting for Kibana at $KIBANA ..."
until curl -fs "$KIBANA/api/status" | grep -q '"level":"available"'; do sleep 5; done

echo "importing saved objects"
curl -fsS -X POST "$KIBANA/api/saved_objects/_import?overwrite=true" \
     -H "kbn-xsrf: true" --form file=@/setup/saved-objects.ndjson
echo
curl -fsS -X POST "$KIBANA/api/data_views/default" \
     -H "kbn-xsrf: true" -H "Content-Type: application/json" \
     -d '{"data_view_id": "jobs-logs", "force": true}'
echo
echo "Kibana saved objects imported."
