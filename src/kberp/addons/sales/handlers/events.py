"""Handlers for sales events, registered at import time."""

from __future__ import annotations

import logging

from ....services.bus import Bus
from ....services.events import register_handler

log = logging.getLogger(__name__)


def on_confirmed(env, payload):
    """Announce a confirmed order; consumers stay behind the outbox."""
    Bus(env.db, env.registry).publish(
        "platform", "sales.order.confirmed", {"order_id": payload.get("order_id")}
    )


def on_cancelled(env, payload):
    Bus(env.db, env.registry).publish(
        "platform", "sales.order.cancelled", {"order_id": payload.get("order_id")}
    )


def on_sent(env, payload):
    Bus(env.db, env.registry).publish(
        "platform", "sales.quotation.sent", {"order_id": payload.get("order_id")}
    )


register_handler("sales.order.confirmed", on_confirmed)
register_handler("sales.order.cancelled", on_cancelled)
register_handler("sales.quotation.sent", on_sent)


def on_delivered(env, payload):
    """Recompute delivered quantities after a picking validation."""
    from ..services.fulfillment import recompute

    orders = env["sales.order"].search([("name", "=", payload.get("origin") or "")])
    if orders:
        recompute(env, orders)


def on_invoiced(env, payload):
    """Recompute invoiced quantities after an invoice posting."""
    from ..services.fulfillment import recompute

    orders = env["sales.order"].search([("name", "=", payload.get("origin") or "")])
    if orders:
        recompute(env, orders)


register_handler("inventory.picking.validated", on_delivered)
register_handler("accounting.move.posted", on_invoiced)
