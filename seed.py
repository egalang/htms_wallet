"""Idempotent HERMES production seed.

Executed by ``odoo shell`` (see entrypoint.sh). The ``env`` variable is injected
by the shell. This runs on every server boot; first-time-only operations are
gated by an ir.config_parameter marker so later UI changes are preserved.
"""

import os


def _param(key, default=''):
    return (os.environ.get(key) or default).strip()


ICP = env['ir.config_parameter'].sudo()

# --- Public base URL --------------------------------------------------------
base_url = _param('ODOO_BASE_URL')
if base_url:
    ICP.set_param('web.base.url', base_url)
    ICP.set_param('web.base.url.freeze', 'True')
    print('[seed] web.base.url =', base_url)

# --- Initial admin credentials (first boot only) ----------------------------
admin_login = _param('HERMES_ADMIN_LOGIN', 'admin')
admin_password = _param('HERMES_ADMIN_PASSWORD')
if admin_password and not ICP.get_param('hermes.seed.admin_done'):
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    if admin:
        admin.write({'login': admin_login, 'password': admin_password})
        ICP.set_param('hermes.seed.admin_done', '1')
        print('[seed] initial admin credentials applied (login=%s)' % admin_login)

# --- PayMongo provider ------------------------------------------------------
sk = _param('PAYMONGO_SECRET_KEY')
wh = _param('PAYMONGO_WEBHOOK_SECRET')
state = _param('PAYMONGO_STATE')

provider = env['payment.provider'].sudo().search([('code', '=', 'paymongo')], limit=1)
if provider:
    vals = {}
    if sk:
        vals['paymongo_secret_key'] = sk
    if wh:
        vals['paymongo_webhook_secret'] = wh
    if state:
        vals['state'] = state
    if vals:
        provider.write(vals)
        print('[seed] paymongo provider updated:', ', '.join(sorted(vals)))

    # QRPH must exist, be active, and be linked to the provider.
    method = env['payment.method'].sudo().search([('code', '=', 'qrph')], limit=1)
    if method:
        if not method.active:
            method.active = True
        if method not in provider.payment_method_ids:
            provider.write({'payment_method_ids': [(4, method.id)]})
        print('[seed] QRPH method id=%s active=%s linked=%s' % (
            method.id, method.active, method in provider.payment_method_ids))
    else:
        print('[seed] WARNING: QRPH payment method not found')

    # Ensure the inbound account.payment.method.line exists for this provider.
    try:
        provider._paymongo_ensure_inbound_method_line()
    except Exception as exc:  # defensive: keep booting even if this changes
        print('[seed] WARNING: could not ensure payment method line:', exc)

    print('[seed] paymongo provider id=%s state=%s' % (provider.id, provider.state))
else:
    print('[seed] WARNING: PayMongo provider not found')

env.cr.commit()
print('[seed] done')
