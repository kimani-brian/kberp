"""Handlers for accounting events."""

from __future__ import annotations

from ....services.bus import Bus
from ....services.events import register_handler


def on_posted(env, payload):
    origin = payload.get("origin") or ""
    if payload.get("move_type") == "out_refund" and origin:
        from ..services.payments import recompute_invoice

        invoices = env["accounting.move"].search(
            [("name", "=", origin), ("move_type", "=", "out_invoice")]
        )
        if invoices:
            recompute_invoice(env, invoices)
    Bus(env.db, env.registry).publish(
        "platform", "accounting.move.posted", {"move_id": payload.get("move_id")}
    )


def on_payment_registered(env, payload):
    Bus(env.db, env.registry).publish(
        "platform",
        "accounting.payment.registered",
        {"payment_id": payload.get("payment_id")},
    )


register_handler("accounting.move.posted", on_posted)
register_handler("accounting.payment.registered", on_payment_registered)
