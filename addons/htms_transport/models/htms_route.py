from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HtmsRoute(models.Model):
    _name = 'htms.route'
    _description = 'HERMES Transport Route'
    _order = 'origin asc, destination asc'

    name = fields.Char(string='Route Name', required=True, index=True)
    origin = fields.Char(string='Origin', required=True)
    destination = fields.Char(string='Destination', required=True)
    distance_km = fields.Float(string='Distance (km)', default=0.0)
    base_price = fields.Monetary(string='Base Price', currency_field='currency_id', default=0.0)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id.id,
    )
    duration_hours = fields.Float(string='Duration (hours)', default=1.0)
    active = fields.Boolean(string='Active', default=True)
    trip_ids = fields.One2many('htms.trip', 'route_id', string='Trips')
    trip_count = fields.Integer(string='Trip Count', compute='_compute_trip_count')

    _route_origin_destination_uniq = models.Constraint(
        'unique(origin, destination)',
        'A route with the same origin and destination already exists.',
    )

    def _compute_trip_count(self):
        trip_data = self.env['htms.trip']._read_group(
            [('route_id', 'in', self.ids)],
            ['route_id'],
            ['route_id'],
        )
        trip_counts = {route.id: count for route, count in trip_data}
        for route in self:
            route.trip_count = trip_counts.get(route.id, 0)

    def action_view_trips(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Trips'),
            'res_model': 'htms.trip',
            'view_mode': 'list,form',
            'domain': [('route_id', 'in', self.ids)],
            'context': {'default_route_id': self.id},
        }

    @api.model
    def search_routes(self, origin=False, destination=False):
        """Public method for JSON-2 API. Returns routes matching origin/destination."""
        domain = []
        if origin:
            domain.append(('origin', 'ilike', origin))
        if destination:
            domain.append(('destination', 'ilike', destination))
        routes = self.search(domain, order='origin asc, destination asc')
        return [
            {
                'id': r.id,
                'name': r.name,
                'origin': r.origin,
                'destination': r.destination,
                'distance_km': r.distance_km,
                'base_price': r.base_price,
                'duration_hours': r.duration_hours,
            }
            for r in routes
        ]

    @api.model
    def get_all_routes(self):
        """Public method for JSON-2 API. Returns all active routes."""
        return self.search_routes()

    def write(self, vals):
        res = super().write(vals)
        if 'active' in vals and not vals.get('active', True):
            self.mapped('trip_ids').write({'state': 'cancelled'})
        return res