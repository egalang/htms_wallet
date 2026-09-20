# HERMES Odoo - Docker Deployment Package

Self-contained production deployment for the HERMES Transport Management System
backend: Odoo 19 + PostgreSQL 16 + Caddy (automatic HTTPS), including the
custom `htms_transport` and `payment_paymongo` addons.

```
docker-compose.yml   db (PostgreSQL) + odoo + caddy
Dockerfile           odoo:19.0 + /mnt/extra-addons + entrypoint
entrypoint.sh        render config -> wait for db -> first-boot install -> seed -> start
seed.py              idempotent seed (base URL, admin, PayMongo, QRPH)
odoo.conf            runtime config TEMPLATE (rendered with envsubst)
Caddyfile            auto-TLS + websocket routing
.env.example         copy to .env and fill in secrets
scripts/             backup.sh, restore.sh, upgrade.sh
addons/              htms_transport, payment_paymongo
```

## 1. Prerequisites (production server)

- Linux host (amd64 or arm64) with Docker Engine 24+ and the Compose v2 plugin.
- A DNS `A` (and optionally `AAAA`) record for `DOMAIN` pointing at the server.
- Inbound TCP 80 and 443 open (and UDP 443 for HTTP/3). No other ports are needed
  publicly; the database is never published.
- Outbound internet access for image pulls, Let's Encrypt, and PayMongo.

## 2. Configure

If your unzip tool did not restore executable bits, fix them once:

```bash
chmod +x entrypoint.sh scripts/*.sh
```

Then:

```bash
cp .env.example .env
$EDITOR .env
```

Set at least: `DOMAIN`, `ACME_EMAIL`, `DB_PASSWORD`, `ODOO_ADMIN_PASSWD`,
`HERMES_ADMIN_PASSWORD`, `ODOO_BASE_URL` (must equal `https://${DOMAIN}`).
Fill `PAYMONGO_SECRET_KEY` / `PAYMONGO_WEBHOOK_SECRET` when you have them and set
`PAYMONGO_STATE` to `test` (sandbox) or `enabled` (live).

`.env` holds secrets. Never commit or share it.

## 3. Deploy

```bash
docker compose up -d --build
docker compose logs -f odoo
```

On first boot the entrypoint:

1. renders `/etc/odoo/odoo.conf` from the environment,
2. waits for PostgreSQL,
3. installs `base`, `htms_transport`, `payment_paymongo` (no demo data) on the
   empty database - module data seeds product categories, top-up products
   (PHP 100 / 500 / 1000), routes, trips, the PayMongo provider and QRPH method,
4. runs `seed.py` (sets `web.base.url`, initial admin, PayMongo keys/state,
   ensures QRPH is active and linked),
5. starts Odoo (workers + gevent websocket).

Caddy obtains a Let's Encrypt certificate for `DOMAIN` automatically.

## 4. Verify

```bash
docker compose ps
curl -I "https://${DOMAIN}/web/login"          # expect 200
docker compose exec -T odoo odoo --config=/etc/odoo/odoo.conf shell -d "${DB_NAME:-htms}" --no-http <<'PY'
p = env['payment.provider'].search([('code', '=', 'paymongo')], limit=1)
print('provider', p.id, p.state, 'linked', p.payment_method_ids.mapped('code'))
print('topups', env['product.template'].search([('name', 'ilike', 'HERMES eWallet Top-Up')]).mapped('name'))
print('base_url', env['ir.config_parameter'].sudo().get_param('web.base.url'))
PY
```

Then open `https://${DOMAIN}` and sign in with `HERMES_ADMIN_LOGIN` /
`HERMES_ADMIN_PASSWORD`.

Re-register the PayMongo webhook at `https://${DOMAIN}/payment/paymongo/webhook`
using the production webhook secret.

## 5. Operations

```bash
docker compose logs -f odoo            # follow logs
docker compose restart odoo            # restart app
docker compose stop                    # stop all
docker compose down                    # stop + remove containers (volumes kept)
docker compose down -v                 # DANGER: also deletes volumes/data
```

### Backups

```bash
scripts/backup.sh                      # writes backups/<db>_<ts>.sql.gz + odoo-data_<ts>.tar.gz
scripts/restore.sh backups/htms_20260101-020000.sql.gz backups/odoo-data_20260101-020000.tar.gz
```

Schedule `scripts/backup.sh` with cron (e.g. nightly) and copy the output off the
host. Test a restore periodically.

### Upgrading the application

```bash
# After replacing the addons/ folder with new code:
docker compose build
docker compose up -d
scripts/upgrade.sh                     # applies DB schema/data changes for custom modules
```

`PAYMONGO` and `payment_paymongo` module data are upgrade-safe: an upgrade will
not reset the provider state or deactivate QRPH.

### Offline / air-gapped servers

On a machine with internet:

```bash
docker compose build
docker save hermes-odoo:19.0 postgres:16 caddy:2 | gzip > hermes-images.tar.gz
```

Copy `hermes-images.tar.gz` plus this folder to the server, then:

```bash
docker load < hermes-images.tar.gz
docker compose up -d
```

## 6. Security notes

- `list_db = False` and `dbfilter = ^<db>$`: the database manager is disabled and
  only the configured database is served.
- The Odoo master password and all credentials come from `.env`; nothing secret
  is baked into the image.
- PostgreSQL has no published port.
- Caddy enforces HTTPS and sets HSTS; HTTP is redirected.
- After go-live, rotate the PayMongo secrets to live values and confirm the
  webhook signature.

## 7. Mobile app (Flutter)

The Flutter app is not part of this container. Rebuild a release against the
production backend:

```bash
flutter build appbundle --release \
  --dart-define=HTMS_BASE_URL=https://<DOMAIN> \
  --dart-define=HTMS_DATABASE=<DB_NAME>
```

## 8. Known limitations

- PayMongo is seeded from `.env`, but a real sandbox/live checkout and webhook
  round-trip should still be validated after deployment.
- This package ships the addons as-is; see `AGENTS.md` in the project for the
  broader roadmap and remaining integration work.
- First boot can take a few minutes (module install). The Odoo healthcheck has a
  180s start period to accommodate this.
