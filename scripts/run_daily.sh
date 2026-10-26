#!/usr/bin/env bash
# Run the daily research job once (briefing + competitor + regulatory refresh).
# Schedule it with launchd (see com.ocra.pipeline.daily.plist.example) or cron.
# The computer must be awake; a closed laptop does not collect updates.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data/logs"
cd "$ROOT/backend"
APP_MODE="${APP_MODE:-live}" "$ROOT/.venv/bin/python" -m app.jobs.daily "$@" >> "$ROOT/data/logs/daily_job.log" 2>&1
