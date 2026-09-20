#!/usr/bin/env bash
#
# Upgrade the HERMES custom modules inside the running Odoo container.
# Rebuild the image first if module code changed:
#   docker compose build && docker compose up -d
# then run this to apply schema/data changes.
#
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
source .env

docker compose exec -T odoo \
    odoo --config=/etc/odoo/odoo.conf -d "$DB_NAME" \
    -u htms_transport,payment_paymongo --stop-after-init --no-http

echo "Restarting Odoo ..."
docker compose restart odoo
echo "Upgrade complete."
