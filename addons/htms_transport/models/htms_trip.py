from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HtmsTrip(models.Model):
    _name = 'htms.trip'
    _description = 'HERMES Transport Trip'
    _order = 'departure_datetime asc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    route_id = fields.Many2one(
        'htms.route', string='Route', required=True, ondelete='cascade', index=True
    )
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, ondelete='restrict'
    )
    departure_datetime = fields.Datetime(string='Departure', required=True, index=True)
    arrival_datetime = fields.Datetime(string='Arrival', required=True)
    duration_hours = fields.Float(
        string='Duration (hours)', compute='_compute_duration', store=True
    )
    bus_name = fields.Char(string='Bus', required=True, default='HERMES Express')
    total_seats = fields.Integer(string='Total Seats', required=True, default=40)
    seat_layout = fields.Char(
        string='Seat Layout',
        default='2+2',
        help='Seat layout configuration: 2+2 (40 seats), 2+1 (30 seats), etc.',
    )
    price = fields.Monetary(
        string='Price', currency_field='currency_id', compute='_compute_price', store=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='product_id.currency_id',
        readonly=True,
    )
    state = fields.Selection(
        [
            ('scheduled', 'Scheduled'),
            ('boarding', 'Boarding'),
            ('departed', 'Departed'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string='State',
        default='scheduled',
        index=True,
    )
    ticket_ids = fields.One2many('htms.ticket', 'trip_id', string='Tickets')
    booked_seats = fields.Integer(
        string='Booked Seats', compute='_compute_seats', store=True
    )
    available_seats = fields.Integer(
        string='Available Seats', compute='_compute_seats', store=True
    )
    taken_seat_names = fields.Char(
        string='Taken Seats', compute='_compute_seat_names', readonly=True
    )

    _arrival_after_departure = models.Constraint(
        'CHECK (arrival_datetime > departure_datetime)',
        'Arrival time must be after departure time.',
    )

    @api.depends('route_id', 'departure_datetime')
    def _compute_name(self):
        for trip in self:
            dep = trip.departure_datetime
            dep_fmt = dep.strftime('%d %b %H:%M') if dep else '--'
            trip.name = f"{trip.route_id.name or 'Route'} · {dep_fmt}"

    @api.depends('departure_datetime', 'arrival_datetime')
    def _compute_duration(self):
        for trip in self:
            try:
                trip.duration_hours = (trip.arrival_datetime - trip.departure_datetime).total_seconds() / 3600
            except TypeError:
                trip.duration_hours = 0.0

    @api.depends('product_id.list_price', 'route_id.base_price')
    def _compute_price(self):
        for trip in self:
            trip.price = trip.product_id.list_price or trip.route_id.base_price or 0.0

    @api.depends('total_seats', 'ticket_ids.state')
    def _compute_seats(self):
        for trip in self:
            booked = len(
                trip.ticket_ids.filtered(lambda t: t.state in ('booked', 'checked_in'))
            )
            trip.booked_seats = booked
            trip.available_seats = max(0, trip.total_seats - booked)

    @api.depends('ticket_ids.seat_number', 'ticket_ids.state')
    def _compute_seat_names(self):
        for trip in self:
            taken = trip.ticket_ids.filtered(
                lambda t: t.state in ('booked', 'checked_in')
            ).mapped('seat_number')
            trip.taken_seat_names = ','.join(taken)

    @api.constrains('departure_datetime')
    def _check_departure_not_past(self):
        for trip in self:
            if trip.id and trip.state not in ('cancelled', 'completed') and trip.departure_datetime < fields.Datetime.now():
                raise ValidationError("Cannot schedule a trip in the past.")

    @api.onchange('route_id')
    def _onchange_route(self):
        if self.route_id:
            self.price = self.route_id.base_price
            self.duration_hours = self.route_id.duration_hours

    def _default_seat_grid(self):
        """Generate the expected seat names based on layout and total seats."""
        if self.seat_layout == '2+1':
            aisle_after = 1
        else:
            aisle_after = 2
        cols = aisle_after + 1
        letters = 'ABCD' if self.seat_layout == '2+2' else 'ABC'
        seats = []
        for row in range(1, (self.total_seats // cols) + 1):
            for col, letter in enumerate(letters[:cols]):
                seats.append(f'{row}{letter}')
        return seats

    def get_seat_layout(self):
        """Public method returning seat map with availability."""
        self.ensure_one()
        taken = set(
            self.ticket_ids.filtered(lambda t: t.state in ('booked', 'checked_in', 'cancelled') and t.seat_number)
            .mapped('seat_number')
        )
        all_seats = self._default_seat_grid()
        return [
            {
                'seat': seat,
                'available': seat not in taken and self.state not in ('departed', 'completed', 'cancelled'),
            }
            for seat in all_seats
        ]

    @api.model
    def search_available_trips(
        self, origin=False, destination=False, travel_date=False
    ):
        """Public method for JSON-2 API.
        Returns trips between origin/destination on the given date with seat availability.
        """
        domain = [('state', 'in', ('scheduled', 'boarding'))]
        if travel_date:
            base = fields.Date.to_date(str(travel_date)[:10])
        else:
            base = fields.Date.today()
        start = fields.Datetime.from_string(f'{base} 00:00:00')
        end = start + timedelta(days=1)
        domain.append(('departure_datetime', '>=', start))
        domain.append(('departure_datetime', '<', end))
        if origin:
            domain.append(('route_id.origin', 'ilike', origin))
        if destination:
            domain.append(('route_id.destination', 'ilike', destination))
        trips = self.search(domain, order='departure_datetime asc')
        return [
            {
                'id': t.id,
                'name': t.name,
                'route_id': t.route_id.id,
                'origin': t.route_id.origin,
                'destination': t.route_id.destination,
                'departure': t.departure_datetime.isoformat(),
                'arrival': t.arrival_datetime.isoformat(),
                'duration_hours': round(t.duration_hours, 1),
                'bus_name': t.bus_name,
                'price': t.price,
                'total_seats': t.total_seats,
                'available_seats': t.available_seats,
                'seat_layout': t.seat_layout,
                'state': t.state,
            }
            for t in trips
        ]

    @api.model
    def get_trip_seats(self, trip_id):
        """Public method for JSON-2 API. Returns seat layout for a trip."""
        trip = self.browse(trip_id)
        if not trip.exists():
            raise ValidationError("Trip not found.")
        return {
            'trip_id': trip.id,
            'name': trip.name,
            'seat_layout': trip.seat_layout,
            'total_seats': trip.total_seats,
            'available_seats': trip.available_seats,
            'seats': trip.get_seat_layout(),
        }