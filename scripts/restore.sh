#!/usr/bin/env bash
#
# Restore a HERMES database dump and (optionally) the Odoo data volume.
#
# Usage: scripts/restore.sh <dump.sql.gz> [odoo-data.tar.gz]
#
# The database is dropped and recreated before the dump is loaded. The stack
# must be running (docker compose up -d).
#
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
source .env

DUMP="${1:?usage: scripts/restore.sh <dump.sql.gz> [odoo-data.tar.gz]}"
VOL_TAR="${2:-}"

echo "Stopping Odoo ..."
docker compose stop odoo

echo "Recreating database '${DB_NAME}' ..."
docker compose exec -T db psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"${DB_NAME}\" WITH (FORCE);" \
    -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";"

echo "Loading dump ${DUMP} ..."
gunzip -c "$DUMP" | docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1

if [ -n "$VOL_TAR" ]; then
    echo "Restoring Odoo data volume from ${VOL_TAR} ..."
    docker compose exec -T odoo tar xzf - -C /var/lib/odoo < "$VOL_TAR"
fi

echo "Starting Odoo ..."
docker compose start odoo

echo "Restore complete."
