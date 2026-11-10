#!/usr/bin/env bash
# Run through the existing app API; never create a second LinkedIn session.
set -euo pipefail
umask 077
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
state="${WORKBENCH_READER_STATE:-$HOME/.local/state/outreach-workbench/reader}"
mkdir -p "$state"
exec 9>"$state/runner.lock"
/usr/bin/flock -n 9 || exit 0
# An operator can pause this schedule without editing cron.
[[ ! -e "$state/PAUSED" ]] || exit 0
cd "$repo"
# Bound retained logs; the database retains job outcomes and CRM reply history.
[[ ! -f "$state/last.log" ]] || mv -f "$state/last.log" "$state/previous.log"
exec /usr/bin/timeout --signal=TERM --kill-after=15s 22m \
  /usr/bin/docker compose exec -T app python -m workbench.reader_job --limit "${WORKBENCH_READER_LIMIT:-100}" >"$state/last.log" 2>&1
