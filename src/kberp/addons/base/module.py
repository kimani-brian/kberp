"""Kernel module: partners, products, metadata, security, settings."""

MANIFEST = {
    "name": "Kernel",
    "summary": "Shared models, metadata and the platform services every app uses",
    "schema": "core",
    "version": "0.1.0",
    "depends": (),
    "application": False,
    "sequence": 1,
    "models": [
        "kberp.addons.base.models.meta",
        "kberp.addons.base.models.partner",
        "kberp.addons.base.models.product",
        "kberp.addons.base.models.user",
        "kberp.addons.base.models.events",
        "kberp.addons.base.models.chatter",
    ],
    "handlers": [
        "kberp.addons.base.handlers",
    ],
    "data": [
        "security/ir.model.access.xml",
        "security/ir.rule.xml",
        "views/product_views.xml",
        "views/event_views.xml",
        "data/settings_menus.xml",
    ],
}
