#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/cte-time/backups}"
DB_PATH="${DB_PATH:-/opt/cte-time/data/cte_time.db}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-90}"
STAMP="$(date +%Y%m%d)" || STAMP=""

log_error() {
  local msg="$1"
  printf '%s\n' "$msg" >&2
  if command -v logger >/dev/null 2>&1; then
    logger -t cte-time-backup "$msg" || true
  fi
}

if [[ -z "$STAMP" ]]; then
  log_error "Failed to generate timestamp; aborting backup"
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  log_error "sqlite3 not found on PATH; please install sqlite3."
  exit 1
fi

if [[ ! -f "$DB_PATH" ]]; then
  log_error "Database file not found: $DB_PATH"
  exit 1
fi

mkdir -p "$BACKUP_DIR" || { log_error "Cannot create backup directory: $BACKUP_DIR"; exit 1; }

LOCK_DIR="$BACKUP_DIR/.backup.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log_error "Another backup process appears to be running (lock at $LOCK_DIR)."
  exit 1
fi
trap 'rm -rf "$LOCK_DIR"' EXIT

sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null 2>&1 || log_error "WAL checkpoint failed, continuing anyway"

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

find "$BACKUP_DIR" -name 'cte_time-*.db' -mtime "+$RETENTION_DAYS" -delete
