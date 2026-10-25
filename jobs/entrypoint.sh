#!/bin/sh
# Batch-job container: seed the database once, run every job once so dashboards
# have data immediately, then hand over to cron (supercronic).
set -eu

CRONTAB=/tmp/crontab
cat > "$CRONTAB" <<EOF
# m  h  dom mon dow  command      (generated from IMPORT/RECONCILE/EXTRACT_EVERY_MIN)
*/${IMPORT_EVERY_MIN:-5} * * * *     run-job import_settlement_file
*/${RECONCILE_EVERY_MIN:-10} * * * * run-job reconcile_transactions
*/${EXTRACT_EVERY_MIN:-15} * * * *   run-job daily_extract
EOF
echo "crontab:" && cat "$CRONTAB"

python -m lab.seed
for job in import_settlement_file reconcile_transactions daily_extract; do
    run-job "$job" || true
done

# -passthrough-logs: the jobs already log JSON; don't wrap each line again.
# Absolute path: as PID 1, supercronic re-executes itself (via argv[0]) to reap
# zombie processes, which fails with a bare command name.
exec /usr/local/bin/supercronic -passthrough-logs "$CRONTAB"
