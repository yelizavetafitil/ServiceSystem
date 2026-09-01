#!/bin/sh
# Monthly backup script (TZ 5.5.2)
set -e
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/app/data/backups}
mkdir -p "$BACKUP_DIR"

echo "[backup] DB dump..."
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$BACKUP_DIR/db_${TS}.sql.gz"

echo "[backup] Uploads archive..."
tar -czf "$BACKUP_DIR/uploads_${TS}.tar.gz" -C /app/data uploads 2>/dev/null || true

# Keep last 3 archives of each type
ls -t "$BACKUP_DIR"/db_*.sql.gz 2>/dev/null | tail -n +4 | xargs -r rm -f
ls -t "$BACKUP_DIR"/uploads_*.tar.gz 2>/dev/null | tail -n +4 | xargs -r rm -f

echo "[backup] Done: $BACKUP_DIR"
