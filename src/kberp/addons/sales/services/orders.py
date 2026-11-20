"""Sales order transitions. Every entry point owns one transaction."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....config import Settings
from ....env import Env
from ....orm.model import ConflictError, ValidationError
from ....services.actions import object_action
from ....services.events import emit
from ....services.mail import send_report
from ...inventory.services.api import cancel_deliveries, create_delivery
from .reports import quotation_html

MODEL = "sales.order"


def _log(env: Env, order_id: int, body: str) -> None:
    audit = Env(env.db, registry=env.registry, uid=env.uid, su=True)
    audit["chatter.message"].create(
        {
            "model": MODEL,
            "res_id": order_id,
            "body": body,
            "author_id": env.uid,
            "message_type": "note",
        }
    )


def _read(env: Env, order_id: int) -> dict[str, Any]:
    rows = env["sales.order"].read([order_id])
    if not rows:
        raise ValidationError("the quotation no longer exists")
    return rows[0]


def _delivery_lines(order: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for line in order.get("order_line", []):
        product = line.get("product_id") or {}
        uom = line.get("uom_id") or {}
        result.append(
            {
                "product_id": product.get("id") if isinstance(product, dict) else product,
                "name": line.get("name"),
                "qty": line.get("qty", 0),
                "uom_id": uom.get("id") if isinstance(uom, dict) else uom,
                "note": line.get("note") or "",
            }
        )
    return result


def _require_state(order: dict[str, Any], allowed: tuple[str, ...], action: str) -> None:
    if order["state"] not in allowed:
        raise ConflictError(f"cannot {action} a {order['state']} order")


@object_action(MODEL, "action_send")
def send(env: Env, order_id: int) -> dict[str, Any]:
    """Mark a draft quotation as sent. Preconditions: state is draft."""
    order = _read(env, order_id)
    _require_state(order, ("draft",), "send")
    partner = order.get("partner_id") or {}
    partner_id = partner.get("id") if isinstance(partner, dict) else partner
    partner_row = env["core.partner"].read([int(partner_id)])[0] if partner_id else {}
    html = quotation_html(env, order_id)
    saved = send_report(
        Settings.from_env().mail_dir,
        recipient=partner_row.get("email") or "unspecified@example.test",
        subject=f"Quotation {order['name']}",
        body="Please find the quotation attached.",
        attachment_name=f"{order['name']}.html",
        attachment_html=html,
        metadata={"order_id": order_id, "partner_id": partner_id},
    )
    env["sales.order"].write([order_id], {"state": "sent"})
    _log(env, order_id, "Quotation sent with attachment.")
    emit(
        env,
        "sales.quotation.sent",
        {"order_id": order_id, "partner_id": partner_id, "message_file": saved.name},
    )
    return {
        "ok": True,
        "message": "Quotation sent with attachment.",
        "state": "sent",
        "message_file": saved.name,
    }


@object_action(MODEL, "action_confirm")
def confirm(env: Env, order_id: int) -> dict[str, Any]:
    """Confirm a quotation and request its delivery in the same transaction.

    Preconditions: state is draft or sent and the order has at least one line.
    Side effects: one draft picking per warehouse group, a state change, a
    chatter note and a `sales.order.confirmed` outbox event.
    """
    order = _read(env, order_id)
    _require_state(order, ("draft", "sent"), "confirm")
    if not order.get("order_line"):
        raise ValidationError("add at least one order line before confirming")
    company = order.get("company_id") or {}
    company_id = company.get("id") if isinstance(company, dict) else company
    partner = order.get("partner_id") or {}
    partner_id = partner.get("id") if isinstance(partner, dict) else partner
    if not partner_id:
        raise ValidationError("the quotation has no customer")
    partner_id = int(partner_id)
    picking_id = create_delivery(
        env,
        origin=order["name"],
        partner_id=int(partner_id),
        company_id=company_id,
        lines=_delivery_lines(order),
        scheduled_date=dt.date.today() + dt.timedelta(days=7),
    )
    env["sales.order"].write(
        [order_id], {"state": "sale", "date_order": dt.datetime.now(dt.UTC)}
    )
    _log(env, order_id, "Quotation confirmed. Delivery requested.")
    emit(
        env,
        "sales.order.confirmed",
        {
            "order_id": order_id,
            "partner_id": int(partner_id),
            "company_id": company_id,
            "picking_id": picking_id,
        },
    )
    return {"ok": True, "message": "Sales order confirmed.", "state": "sale"}


@object_action(MODEL, "action_cancel")
def cancel(env: Env, order_id: int) -> dict[str, Any]:
    """Cancel an order and every delivery that has not been completed."""
    order = _read(env, order_id)
    _require_state(order, ("draft", "sent", "sale"), "cancel")
    cancelled = cancel_deliveries(env, origin=order["name"])
    env["sales.order"].write([order_id], {"state": "cancel"})
    _log(env, order_id, "Order cancelled.")
    emit(
        env,
        "sales.order.cancelled",
        {"order_id": order_id, "partner_id": order["partner_id"]["id"]},
    )
    return {
        "ok": True,
        "message": "Order cancelled.",
        "state": "cancel",
        "pickings_cancelled": cancelled,
    }


@object_action(MODEL, "action_reset")
def reset_draft(env: Env, order_id: int) -> dict[str, Any]:
    """Reopen a cancelled order for editing, keeping its number."""
    order = _read(env, order_id)
    _require_state(order, ("cancel",), "reset to draft")
    env["sales.order"].write([order_id], {"state": "draft"})
    _log(env, order_id, "Order reset to draft.")
    return {"ok": True, "message": "Order reset to draft.", "state": "draft"}


@object_action(MODEL, "action_invoice")
def create_invoice(env: Env, order_id: int):
    from .fulfillment import create_invoice as build

    return build(env, order_id)


@object_action(MODEL, "action_lock")
def lock(env: Env, order_id: int):
    from .fulfillment import lock as change

    return change(env, order_id, locked=True)


@object_action(MODEL, "action_unlock")
def unlock(env: Env, order_id: int):
    from .fulfillment import lock as change

    return change(env, order_id, locked=False)
