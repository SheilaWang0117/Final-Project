#!/usr/bin/env bash
# Start the app on http://127.0.0.1:8000 (single process, no auto-reload).
# Usage: scripts/start.sh            -> uses APP_MODE from .env (default demo)
#        APP_MODE=live scripts/start.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "Building the frontend once..."
  (cd "$ROOT/frontend" && npm run build)
fi
cd "$ROOT/backend"
exec "$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000
