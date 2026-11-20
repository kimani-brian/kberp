"""Inventory application."""

MANIFEST = {
    "name": "Inventory",
    "summary": "Warehouses, transfers, stock and valuation",
    "schema": "inventory",
    "version": "0.1.0",
    "depends": ("base",),
    "application": True,
    "sequence": 140,
    "web_icon": "inventory",
    "models": [
        "kberp.addons.inventory.models.picking",
        "kberp.addons.inventory.models.audit",
        "kberp.addons.inventory.models.procurement",
    ],
    "handlers": [
        "kberp.addons.inventory.services.actions",
        "kberp.addons.inventory.services.procurement",
        "kberp.addons.inventory.services.valuation",
        "kberp.addons.inventory.handlers.events",
    ],
    "data": [
        "security/access.xml",
        "views/stock_views.xml",
        "views/audit_views.xml",
        "views/i3_views.xml",
        "data/sequences.xml",
        "data/menus.xml",
    ],
}
