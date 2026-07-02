#!/usr/bin/env bash
set -euo pipefail

if ! command -v sqlite3 &>/dev/null; then
  echo "sqlite3 not found on PATH; please install sqlite3."
  exit 1
fi

BACKUP_DIR="/opt/cte-time/backups"
DB_PATH="/opt/cte-time/data/cte_time.db"
STAMP="$(date +%Y%m%d)"
BACKUP_FILE="${BACKUP_DIR}/cte_time-${STAMP}.db"

mkdir -p "${BACKUP_DIR}"

sqlite3 "${DB_PATH}" ".backup ${BACKUP_FILE}"

echo "Backup created: ${BACKUP_FILE}"
