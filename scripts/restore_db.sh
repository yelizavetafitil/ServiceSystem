#!/bin/sh
# Restore schema + demo data from database/servicesystem_seed.sql
# Usage (Docker):
#   docker compose up -d db
#   docker compose exec -T db psql -U servicesystem -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'servicesystem' AND pid <> pg_backend_pid();"
#   docker compose exec -T db psql -U servicesystem -d postgres -c "DROP DATABASE IF EXISTS servicesystem;"
#   docker compose exec -T db psql -U servicesystem -d postgres -c "CREATE DATABASE servicesystem;"
#   docker compose exec -T db psql -U servicesystem -d servicesystem < database/servicesystem_seed.sql
set -e
DUMP=${1:-database/servicesystem_seed.sql}
if [ ! -f "$DUMP" ]; then
  echo "Dump not found: $DUMP"
  exit 1
fi
echo "[restore] Loading $DUMP into servicesystem..."
PGPASSWORD="${POSTGRES_PASSWORD:-servicesystem}" psql -h "${POSTGRES_HOST:-db}" -U "${POSTGRES_USER:-servicesystem}" -d postgres -v ON_ERROR_STOP=1 <<EOF
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'servicesystem' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS servicesystem;
CREATE DATABASE servicesystem;
EOF
PGPASSWORD="${POSTGRES_PASSWORD:-servicesystem}" psql -h "${POSTGRES_HOST:-db}" -U "${POSTGRES_USER:-servicesystem}" -d servicesystem -v ON_ERROR_STOP=1 -f "$DUMP"
echo "[restore] Done."
