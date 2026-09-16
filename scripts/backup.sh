#!/bin/sh
# Monthly backup script (TZ 5.5.2) — DB + uploads, keep last 3 archives
set -e
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/app/data/backups}
mkdir -p "$BACKUP_DIR" /app/data

echo "[backup] DB dump..."
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$BACKUP_DIR/db_${TS}.sql.gz"

echo "[backup] Uploads archive..."
tar -czf "$BACKUP_DIR/uploads_${TS}.tar.gz" -C /app/data uploads 2>/dev/null || true

prune_old() {
  pattern="$1"
  count=0
  for f in $(ls -t $pattern 2>/dev/null); do
    count=$((count + 1))
    if [ "$count" -gt 3 ]; then
      rm -f "$f"
    fi
  done
}

prune_old "$BACKUP_DIR/db_*.sql.gz"
prune_old "$BACKUP_DIR/uploads_*.tar.gz"

echo "[backup] Done: $BACKUP_DIR"
