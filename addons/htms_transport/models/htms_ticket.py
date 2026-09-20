import qrcode
from io import BytesIO
from uuid import uuid4

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HtmsTicket(models.Model):
    _name = 'htms.ticket'
    _description = 'HERMES Transport Ticket'
    _order = 'create_date desc'

    name = fields.Char(string='Booking Reference', required=True, index=True, copy=False)
    trip_id = fields.Many2one(
        'htms.trip', string='Trip', required=True, ondelete='cascade', index=True
    )
    route_name = fields.Char(string='Route', related='trip_id.route_id.name', store=True)
    origin = fields.Char(string='Origin', related='trip_id.route_id.origin', store=True)
    destination = fields.Char(string='Destination', related='trip_id.route_id.destination', store=True)
    departure_datetime = fields.Datetime(string='Departure', related='trip_id.departure_datetime', store=True)
    bus_name = fields.Char(string='Bus', related='trip_id.bus_name', store=True)
    partner_id = fields.Many2one(
        'res.partner', string='Passenger', required=True, ondelete='restrict', index=True
    )
    seat_number = fields.Char(string='Seat', required=True, index=True)
    price = fields.Monetary(string='Price', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', string='Currency', default=lambda self: self.env.company.currency_id.id
    )
    order_id = fields.Many2one('sale.order', string='Sales Order', ondelete='set null')
    state = fields.Selection(
        [
            ('booked', 'Booked'),
            ('confirmed', 'Confirmed'),
            ('checked_in', 'Checked In'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string='State',
        default='booked',
        index=True,
    )
    qr_value = fields.Char(string='QR Content', copy=False)
    checked_in_datetime = fields.Datetime(string='Checked In At', readonly=True)

    _seat_unique_per_trip = models.Constraint(
        'unique(trip_id, seat_number)',
        'A seat can only be booked once per trip.',
    )

    @api.model
    def _default_name(self):
        return f'HMS-{str(uuid4()).upper()[:8]}'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self._generate_unique_reference()
            if not vals.get('qr_value'):
                vals['qr_value'] = vals['name']
            if not vals.get('price'):
                trip = self.env['htms.trip'].browse(vals.get('trip_id'))
                if trip:
                    vals['price'] = trip.price
        return super().create(vals_list)

    def _generate_unique_reference(self):
        while True:
            ref = f'HMS-{str(uuid4()).upper()[:8]}'
            if not self.search_count([('name', '=', ref)]):
                return ref

    def action_confirm(self):
        """Web/backend confirmation path."""
        for ticket in self:
            if ticket.state != 'booked':
                raise UserError("Only booked tickets can be confirmed.")
            if ticket.trip_id.state not in ('scheduled', 'boarding'):
                raise UserError("This trip is no longer accepting bookings.")
            if ticket.trip_id.available_seats <= 0:
                raise UserError("No seats available for this trip.")
            if ticket.order_id and ticket.order_id.state == 'draft':
                ticket.order_id.action_confirm()
            ticket.state = 'confirmed'

    def action_check_in(self):
        for ticket in self:
            if ticket.state != 'confirmed':
                raise UserError("Only confirmed tickets can be checked in.")
            ticket._check_valid_for_boarding()
            ticket.write({'state': 'checked_in', 'checked_in_datetime': fields.Datetime.now()})

    def action_cancel(self):
        for ticket in self:
            ticket.state = 'cancelled'
            if ticket.order_id and ticket.order_id.state in ('draft', 'sent'):
                ticket.order_id.action_cancel()

    def _check_valid_for_boarding(self):
        now = fields.Datetime.now()
        if self.departure_datetime < now:
            raise UserError("This trip has already departed.")

    @api.model
    def book_trip(self, partner_id, trip_id, seat_number, use_ewallet=True):
        """Public method for JSON-2 API. Books a seat and creates/confirms the sale order.
        If use_ewallet is True, pays with the partner's eWallet if available.
        """
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            raise ValidationError("Partner not found.")
        trip = self.env['htms.trip'].browse(trip_id)
        if not trip.exists():
            raise ValidationError("Trip not found.")

        if trip.state not in ('scheduled', 'boarding'):
            raise ValidationError("This trip is no longer accepting bookings.")
        if trip.available_seats <= 0:
            raise ValidationError("No seats available for this trip.")
        if self.search_count([('trip_id', '=', trip.id), ('seat_number', '=', seat_number)]):
            raise ValidationError(f"Seat {seat_number} is already taken.")

        ticket = self.create(
            {
                'trip_id': trip.id,
                'partner_id': partner.id,
                'seat_number': seat_number,
                'price': trip.price,
            }
        )

        order = self.env['sale.order'].with_context(use_ewallet=use_ewallet).create(
            {
                'partner_id': partner.id,
                'order_line': [
                    (
                        0,
                        0,
                        {
                            'product_id': trip.product_id.id,
                            'product_uom_qty': 1,
                            'name': f"{trip.name} · Seat {seat_number}",
                        },
                    )
                ],
                'note': f"HERMES Transport Booking {ticket.name} - Seat {seat_number}",
            }
        )
        ticket.order_id = order.id

        if use_ewallet:
            try:
                order.action_confirm()
                ticket.state = 'confirmed'
            except Exception as e:
                order.action_cancel()
                ticket.state = 'cancelled'
                raise ValidationError(f"Payment failed: {e}")
        else:
            order.state = 'sale'

        return {
            'ticket_id': ticket.id,
            'reference': ticket.name,
            'trip': ticket.trip_id.name,
            'origin': ticket.origin,
            'destination': ticket.destination,
            'departure': ticket.departure_datetime.isoformat() if ticket.departure_datetime else False,
            'bus': ticket.bus_name,
            'seat': ticket.seat_number,
            'price': ticket.price,
            'qr_value': ticket.qr_value,
            'state': ticket.state,
            'order_id': order.id,
        }

    @api.model
    def cancel_booking(self, ticket_id):
        """Public method for JSON-2 API. Cancels a ticket and refunds wallet if paid by eWallet."""
        ticket = self.browse(ticket_id)
        if not ticket.exists():
            raise ValidationError("Ticket not found.")
        ticket.action_cancel()
        return {'success': True, 'reference': ticket.name, 'state': ticket.state}

    @api.model
    def get_my_tickets(self, partner_id, state=False):
        """Public method for JSON-2 API. Returns tickets for a partner."""
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            raise ValidationError("Partner not found.")
        domain = [('partner_id', '=', partner.id)]
        if state:
            domain.append(('state', '=', state))
        tickets = self.search(domain, order='create_date desc')
        return [
            {
                'id': t.id,
                'reference': t.name,
                'origin': t.origin,
                'destination': t.destination,
                'departure': t.departure_datetime.isoformat() if t.departure_datetime else False,
                'bus': t.bus_name,
                'seat': t.seat_number,
                'price': t.price,
                'state': t.state,
                'qr_value': t.qr_value,
            }
            for t in tickets
        ]

    def get_qr_base64(self):
        """Return a base64-encoded QR code PNG for the ticket."""
        self.ensure_one()
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(self.qr_value or self.name)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue().hex()

    # ------------------------------------------------------------------
    # Wallet top-up
    # ------------------------------------------------------------------

    @api.model
    def top_up_wallet(self, partner_id, amount):
        """Create a PayMongo checkout session for a wallet top-up.

        Returns {'checkout_url': ..., 'order_name': ...} so the mobile app
        can open the PayMongo hosted checkout in a browser.
        """
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            raise ValidationError("Partner not found.")

        # Find the matching top-up product by list_price.
        product = self.env['product.product'].search([
            ('name', 'ilike', 'HERMES eWallet Top-Up'),
            ('list_price', '=', amount),
        ], limit=1)
        if not product:
            raise ValidationError(
                f"No top-up product priced at PHP {amount:.0f}."
            )

        provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'paymongo'), ('state', '!=', 'disabled')],
            limit=1,
        )
        if not provider:
            raise ValidationError("PayMongo provider is not configured.")

        # Create the sale order (draft) and link the payment transaction.
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1,
                'name': product.name,
            })],
        })

        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': provider.payment_method_ids[0].id if provider.payment_method_ids else False,
            'amount': amount,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': partner.id,
            'reference': order.name,
            'operation': 'online_redirect',
            'sale_order_ids': [(4, order.id)],
        })

        # Create the PayMongo checkout session and grab the hosted-checkout URL.
        try:
            specific = tx.sudo()._get_specific_rendering_values({})
            checkout_url = specific.get('api_url')
        except Exception:
            checkout_url = None

        if not checkout_url:
            raise ValidationError(
                "Could not create a PayMongo checkout session."
            )

        return {
            'checkout_url': checkout_url,
            'order_name': order.name,
        }

    @api.model
    def get_wallet_history(self, partner_id):
        """Return recent loyalty-history rows for the partner's eWallet card.

        Each row: {type, amount, description, date}
          type  : 'topup' when points were issued, 'debit' when used
          amount: signed PHP value (+ for top-up, - for spend)
        """
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            return []

        card = self.env['loyalty.card'].search(
            [('partner_id', '=', partner.id)], limit=1,
        )
        if not card:
            return []

        rows = self.env['loyalty.history'].search_read(
            [('card_id', '=', card.id)],
            fields=['issued', 'used', 'description', 'create_date'],
            order='create_date desc',
            limit=50,
        )
        result = []
        for r in rows:
            issued = float(r.get('issued') or 0)
            used = float(r.get('used') or 0)
            net = issued - used
            result.append({
                'type': 'topup' if issued > 0 else 'debit',
                'amount': net,
                'description': r.get('description') or '',
                'date': r.get('create_date') or '',
            })
        return result