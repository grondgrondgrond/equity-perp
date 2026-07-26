#!/usr/bin/env bash
# Hourly options-snapshot cron entry (equity-perp). Pattern follows the
# predict/compute-pricing boxes: collect -> s3 sync -> prune local -> heartbeat.
#
# Required env (set in crontab):
#   EQUITY_PERP_S3   e.g. s3://equity-deriv-trading/options   (destination prefix)
# Optional:
#   HEALTHCHECK_URL  healthchecks.io ping URL (skipped if unset)
#   EOD=1            tag this run as the canonical daily snapshot (22:00 UTC entry)
#
# Crontab (append, don't replace — see compute-pricing/deploy/README.md):
#   5 * * * *  cd $HOME/equity-perp && bash scripts/cron_collect.sh >> $HOME/cron/equity-perp.log 2>&1
#   0 22 * * * cd $HOME/equity-perp && EOD=1 bash scripts/cron_collect.sh >> $HOME/cron/equity-perp.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

ARGS=""
[ "${EOD:-0}" = "1" ] && ARGS="eod"
.venv/bin/python scripts/collect_options.py $ARGS

if [ -n "${EQUITY_PERP_S3:-}" ]; then
  aws s3 sync data/raw/options/ "$EQUITY_PERP_S3/" --only-show-errors
  # local buffer: keep 7 days once safely synced
  find data/raw/options -maxdepth 1 -type d -name '20*' -mtime +7 -exec rm -rf {} +
fi

[ -n "${HEALTHCHECK_URL:-}" ] && curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL" >/dev/null
echo "$(date -u +%FT%TZ) cron_collect OK"
