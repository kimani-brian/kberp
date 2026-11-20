"""Handlers for purchase events and inventory feedback."""

from __future__ import annotations

from ....services.bus import Bus
from ....services.events import register_handler


def on_receipt_validated(env, payload):
    from ..services.billing import recompute

    orders = env["purchase.order"].search([("name", "=", payload.get("origin") or "")])
    if orders:
        recompute(env, orders)


def on_bill_posted(env, payload):
    from ..services.billing import recompute

    orders = env["purchase.order"].search([("name", "=", payload.get("origin") or "")])
    if orders:
        recompute(env, orders)


def on_confirmed(env, payload):
    Bus(env.db, env.registry).publish(
        "platform", "purchase.order.confirmed", {"order_id": payload.get("order_id")}
    )


def on_cancelled(env, payload):
    Bus(env.db, env.registry).publish(
        "platform", "purchase.order.cancelled", {"order_id": payload.get("order_id")}
    )


register_handler("inventory.picking.validated", on_receipt_validated)
register_handler("accounting.move.posted", on_bill_posted)
register_handler("purchase.order.confirmed", on_confirmed)
register_handler("purchase.order.cancelled", on_cancelled)
