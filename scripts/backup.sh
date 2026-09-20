#!/usr/bin/env bash
#
# Back up the HERMES database and Odoo data volume (filestore/sessions).
# Usage: scripts/backup.sh [output_dir]
#
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
source .env

OUT="${1:-backups}"
mkdir -p "$OUT"

STAMP="$(date +%Y%m%d-%H%M%S)"

echo "Dumping database '${DB_NAME}' ..."
docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" \
    | gzip > "${OUT}/${DB_NAME}_${STAMP}.sql.gz"

echo "Archiving Odoo data volume ..."
docker compose exec -T odoo tar czf - -C /var/lib/odoo . \
    > "${OUT}/odoo-data_${STAMP}.tar.gz"

echo "Backup written to ${OUT}/"
ls -lh "${OUT}"/*"${STAMP}"*
