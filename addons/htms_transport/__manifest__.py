{
    'name': 'HERMES Transport',
    'version': '0.1.0',
    'summary': 'Bus trip booking, e-wallet transport and tickets',
    'sequence': 10,
    'description': """
HERMES Transport Management System
==================================
Custom Odoo module for HERMES bus transport:
* Route management (origin, destination, price, duration)
* Trip scheduling (departure/arrival times, seat capacity)
* Seat reservations and ticket booking
* Integration with eWallet / gift card payments
* Public JSON-2 API for mobile app integration
""",
    'category': 'Sales',
    'website': 'https://hermes.local',
    'author': 'HERMES TMS',
    'depends': ['sale', 'account', 'website_sale', 'product', 'loyalty'],
    'data': [
        'security/ir.model.access.csv',
        'security/rule_ticket.xml',
        'data/routes_data.xml',
        'data/trips_data.xml',
        'views/htms_route_views.xml',
        'views/htms_trip_views.xml',
        'views/htms_ticket_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}