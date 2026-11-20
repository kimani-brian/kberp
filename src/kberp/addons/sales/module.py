"""Sales application."""

MANIFEST = {
    "name": "Sales",
    "summary": "Quotations, orders, products and sales reporting",
    "schema": "sales",
    "version": "0.1.0",
    "depends": ("base", "accounting", "inventory"),
    "application": True,
    "sequence": 30,
    "web_icon": "sales",
    "models": [
        "kberp.addons.sales.models.settings",
        "kberp.addons.sales.models.config",
        "kberp.addons.sales.models.order",
    ],
    "handlers": [
        "kberp.addons.sales.services.orders",
        "kberp.addons.sales.handlers.events",
    ],
    "data": [
        "security/access.xml",
        "views/sale_views.xml",
        "views/settings_views.xml",
        "views/config_views.xml",
        "data/sequences.xml",
        "data/menus.xml",
    ],
}
