"""Handlers for inventory events."""

from __future__ import annotations

from ....services.bus import Bus
from ....services.events import register_handler


def on_validated(env, payload):
    from ..services.valuation import value_picking

    if payload.get("picking_id"):
        value_picking(env, int(payload["picking_id"]))
    Bus(env.db, env.registry).publish(
        "platform", "inventory.picking.validated", {"picking_id": payload.get("picking_id")}
    )


def on_adjustment(env, payload):
    Bus(env.db, env.registry).publish("platform", "inventory.adjusted", payload)


def on_scrapped(env, payload):
    Bus(env.db, env.registry).publish("platform", "inventory.scrapped", payload)


register_handler("inventory.picking.validated", on_validated)
def on_valuation(env, payload):
    Bus(env.db, env.registry).publish("platform", "inventory.valuation.created", payload)


register_handler("inventory.valuation.created", on_valuation)
register_handler("inventory.count.validated", on_adjustment)
register_handler("inventory.scrap.validated", on_scrapped)
