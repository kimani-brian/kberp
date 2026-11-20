"""Purchase application."""

MANIFEST = {
    "name": "Purchase",
    "summary": "Requests for quotation, purchase orders and vendor bills",
    "schema": "purchase",
    "version": "0.1.0",
    "depends": ("base", "accounting", "inventory"),
    "application": True,
    "sequence": 135,
    "web_icon": "purchase",
    "models": [
        "kberp.addons.purchase.models.order",
        "kberp.addons.purchase.models.agreement",
    ],
    "handlers": [
        "kberp.addons.purchase.services.orders",
        "kberp.addons.purchase.services.actions",
        "kberp.addons.purchase.handlers.events",
    ],
    "data": [
        "security/access.xml",
        "views/purchase_views.xml",
        "views/agreement_views.xml",
        "data/purchase_data.xml",
        "data/menus.xml",
    ],
}
