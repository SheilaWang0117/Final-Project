#!/usr/bin/env bash
# Consistent SQLite backup of the configured database (default: live database).
# Usage: scripts/backup.sh [path/to/database.db]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="${1:-$ROOT/data/ocra_live.db}"
mkdir -p "$ROOT/data/backups"
OUT="$ROOT/data/backups/$(basename "$DB" .db)_$(date +%Y%m%d_%H%M%S).db"
sqlite3 "$DB" ".backup '$OUT'"
echo "Backup written to $OUT (contains confidential data; store securely)."
