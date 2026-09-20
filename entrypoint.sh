#!/usr/bin/env bash
#
# HERMES Odoo entrypoint.
#
#  1. Render /etc/odoo/odoo.conf from the environment.
#  2. Wait for PostgreSQL.
#  3. On an empty database, install base + HERMES modules (no demo data).
#  4. Run the idempotent seed script (base URL, admin, PayMongo).
#  5. Start Odoo (or run the requested subcommand).
#
set -euo pipefail

log() { printf '[hermes-entrypoint] %s\n' "$*" >&2; }

# --- Environment -----------------------------------------------------------
: "${DB_HOST:=db}"
: "${DB_PORT:=5432}"
: "${DB_USER:=odoo}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DB_NAME:=htms}"
: "${ODOO_ADMIN_PASSWD:?ODOO_ADMIN_PASSWD is required}"
: "${ODOO_WORKERS:=4}"
: "${ODOO_MAX_CRON_THREADS:=2}"
: "${ODOO_LOG_LEVEL:=info}"
: "${HERMES_EXTRA_MODULES:=htms_transport,payment_paymongo}"

export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
export ODOO_ADMIN_PASSWD ODOO_WORKERS ODOO_MAX_CRON_THREADS ODOO_LOG_LEVEL

ODOO_RC=/etc/odoo/odoo.conf

# --- 1. Render config ------------------------------------------------------
envsubst '${ODOO_ADMIN_PASSWD} ${DB_HOST} ${DB_PORT} ${DB_USER} ${DB_PASSWORD} ${DB_NAME} ${ODOO_WORKERS} ${ODOO_MAX_CRON_THREADS} ${ODOO_LOG_LEVEL}' \
    < /opt/hermes/odoo.conf.template > "$ODOO_RC"
log "Rendered configuration at $ODOO_RC"

# --- Decide whether this is a server boot (run init/seed) or a one-off command
RUN_INIT=1
case "${1:-}" in
    ""|odoo|--) ;;
    *) RUN_INIT=0 ;;
esac
if [ "${1:-}" = "odoo" ] || [ "${1:-}" = "--" ]; then
    shift
fi

# --- 2. Wait for PostgreSQL ------------------------------------------------
log "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT} ..."
ready=0
for _ in $(seq 1 60); do
    if PGPASSWORD="$DB_PASSWORD" pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; then
        ready=1
        break
    fi
    sleep 2
done
if [ "$ready" != "1" ]; then
    log "ERROR: PostgreSQL not reachable after 120s"
    exit 1
fi
log "PostgreSQL is ready"

# --- 3./4. First boot install + seed --------------------------------------
if [ "$RUN_INIT" = "1" ]; then
    db_exists="$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null || true)"

    initialized=0
    if [ "$db_exists" = "1" ]; then
        has_table="$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
            "SELECT to_regclass('public.ir_module_module') IS NOT NULL" 2>/dev/null || echo "f")"
        if [ "$has_table" = "t" ]; then
            initialized=1
        fi
    fi

    if [ "$initialized" = "0" ]; then
        log "Database '${DB_NAME}' is not initialized - installing modules: base,${HERMES_EXTRA_MODULES}"
        odoo --config="$ODOO_RC" -d "$DB_NAME" \
            -i "base,${HERMES_EXTRA_MODULES}" \
            --without-demo=all --stop-after-init --no-http
        log "Module installation finished"
    else
        log "Database '${DB_NAME}' already initialized"
    fi

    if [ -f /opt/hermes/seed.py ]; then
        log "Running seed script"
        odoo --config="$ODOO_RC" shell -d "$DB_NAME" --no-http < /opt/hermes/seed.py \
            || log "WARNING: seed script exited non-zero (continuing)"
    fi
else
    log "One-off command detected - skipping install/seed"
fi

# --- 5. Start --------------------------------------------------------------
log "Executing: odoo --config=$ODOO_RC $*"
exec odoo --config="$ODOO_RC" "$@"
