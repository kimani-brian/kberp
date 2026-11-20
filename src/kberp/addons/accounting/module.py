"""Accounting application."""

MANIFEST = {
    "name": "Accounting",
    "summary": "Ledgers, invoices, payments, closing and reports",
    "schema": "accounting",
    "version": "0.1.0",
    "depends": ("base",),
    "application": True,
    "sequence": 60,
    "web_icon": "accounting",
    "models": [
        "kberp.addons.accounting.models.tax",
        "kberp.addons.accounting.models.ledger",
        "kberp.addons.accounting.models.payment",
        "kberp.addons.accounting.models.closing",
    ],
    "handlers": [
        "kberp.addons.accounting.services.actions",
        "kberp.addons.accounting.services.closing",
        "kberp.addons.accounting.services.reporting",
        "kberp.addons.accounting.handlers.events",
        "kberp.addons.accounting.handlers.closing",
    ],
    "data": [
        "security/access.xml",
        "data/taxes.xml",
        "views/ledger_views.xml",
        "views/closing_views.xml",
        "data/closing_data.xml",
        "data/menus.xml",
    ],
}
