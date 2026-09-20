# HERMES Transport Management System - Odoo production image
#
# Base: official Odoo 19 image (Ubuntu + Odoo .deb).
# Adds: custom HERMES addons, runtime config templating, first-boot seeding.
#
# Build from the package root:
#   docker compose build
#   (or: docker build -t hermes-odoo:19.0 .)

FROM odoo:19.0

USER root

# gettext-base -> envsubst, used to render odoo.conf from the environment.
# python3-pil  -> Pillow backend for qrcode ticket generation (htms_transport).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext-base python3-pil \
    && rm -rf /var/lib/apt/lists/*

# Custom HERMES addons
COPY addons/htms_transport /mnt/extra-addons/htms_transport
COPY addons/payment_paymongo /mnt/extra-addons/payment_paymongo

# Runtime config template, entrypoint and seed script
COPY odoo.conf /opt/hermes/odoo.conf.template
COPY entrypoint.sh /usr/local/bin/hermes-entrypoint.sh
COPY seed.py /opt/hermes/seed.py

RUN chmod +x /usr/local/bin/hermes-entrypoint.sh \
    && chown -R odoo:odoo /mnt/extra-addons /opt/hermes /etc/odoo

USER odoo

ENTRYPOINT ["/usr/local/bin/hermes-entrypoint.sh"]
CMD ["odoo"]
