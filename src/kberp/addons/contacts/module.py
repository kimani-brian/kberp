"""Contacts application: directory UI over the kernel partner model."""

MANIFEST = {
    "name": "Contacts",
    "summary": "People and companies, addresses, banks and the contact directory",
    "schema": "contacts",
    "version": "0.1.0",
    "depends": ("base",),
    "application": True,
    "sequence": 20,
    "web_icon": "contacts",
    "models": [],
    "data": [
        "views/partner_views.xml",
        "views/config_views.xml",
        "data/menus.xml",
    ],
}
