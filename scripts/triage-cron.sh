#!/usr/bin/env bash
#
# Cron entry point for the Gmail Triage Agent (GTA-10).
#
# Runs one triage pass via docker compose. Intended to be invoked by cron on
# the host (e.g. every 3 hours); the agent itself owns the incremental window
# and the last-success marker, so this wrapper just launches a run, prevents
# overlap, and records that it fired.
#
# Install (crontab -e), every 3 hours:
#   0 */3 * * * /home/stuart/apps/gmail-triage-agent/scripts/triage-cron.sh
#
# Cron runs with a minimal environment, so we set a sane PATH (docker lives in
# /usr/bin) and cd into the repo before calling compose.

set -uo pipefail

# Repo root = parent of this script's directory.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

LOG_DIR="$REPO_DIR/data/logs"
mkdir -p "$LOG_DIR"
CRON_LOG="$LOG_DIR/cron.log"

# Prevent overlapping runs if one pass outlives the schedule interval.
exec 9>"$LOG_DIR/.cron.lock"
if ! flock -n 9; then
    echo "$(date -Is) another triage run is in progress; skipping" >>"$CRON_LOG"
    exit 0
fi

echo "$(date -Is) starting scheduled triage" >>"$CRON_LOG"

# One-off run; --rm cleans up the container. The agent writes its own detailed
# log to data/logs/triage.log; here we also capture stdout/stderr and the exit
# code for a quick "did cron fire and how did it end" view.
docker compose run --rm agent >>"$CRON_LOG" 2>&1
status=$?

echo "$(date -Is) finished scheduled triage (exit $status)" >>"$CRON_LOG"
exit "$status"
