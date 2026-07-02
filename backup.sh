#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/cte-time/backups}"
DB_PATH="${DB_PATH:-/opt/cte-time/data/cte_time.db}"
STAMP="$(date +%Y%m%d)"

log_error() {
  local msg="$1"
  printf '%s\n' "$msg" >&2
  if command -v logger >/dev/null 2>&1; then
    logger -t cte-time-backup "$msg" || true
  fi
}

if ! command -v sqlite3 >/dev/null 2>&1; then
  log_error "sqlite3 not found on PATH; please install sqlite3."
  exit 1
fi

if [[ ! -f "$DB_PATH" ]]; then
  log_error "Database file not found: $DB_PATH"
  exit 1
fi

mkdir -p "$BACKUP_DIR"

counter=1
while :; do
  backup_file="$BACKUP_DIR/cte_time-$STAMP-$(printf '%04d' "$counter").db"
  if [[ ! -e "$backup_file" ]]; then
    break
  fi
  counter=$((counter + 1))
done

if ! sqlite3 "$DB_PATH" ".backup $backup_file"; then
  log_error "Backup failed for $DB_PATH -> $backup_file"
  exit 1
fi

printf 'Backup created: %s\n' "$backup_file"
