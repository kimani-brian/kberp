"""Purchase order transitions, receipts and status feedback."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....env import Env
from ....orm.model import ConflictError, ValidationError
from ....services.actions import object_action
from ....services.events import emit
from ...inventory.services.api import cancel_receipts, create_receipt

MODEL = "purchase.order"


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
    rows = env["purchase.order"].read([order_id])
    if not rows:
        raise ValidationError("the quotation no longer exists")
    return rows[0]


def _require_state(order: dict[str, Any], allowed: tuple[str, ...], action: str) -> None:
    if order["state"] not in allowed:
        raise ConflictError(f"cannot {action} a {order['state']} order")


def _settings(env: Env) -> dict[str, Any]:
    ids = env["purchase.settings"].search([], limit=1)
    return env["purchase.settings"].read([ids[0]])[0] if ids else {}


def _is_manager(env: Env) -> bool:
    if env.su or (env.user or {}).get("is_admin"):
        return True
    groups = (env.user or {}).get("group_xmlids") or []
    return "purchase.group_purchase_manager" in groups


def _approval_required(env: Env, order: dict[str, Any]) -> bool:
    if order.get("approval_state") == "approved":
        return False
    threshold = float(_settings(env).get("approval_threshold") or 0)
    if threshold <= 0:
        return False
    if float(order.get("amount_total") or 0) <= threshold:
        return False
    return not _is_manager(env)


def _receipt_lines(order: dict[str, Any]) -> list[dict[str, Any]]:
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
            }
        )
    return result


@object_action(MODEL, "action_send")
def send(env: Env, order_id: int) -> dict[str, Any]:
    order = _read(env, order_id)
    _require_state(order, ("draft",), "send")
    env["purchase.order"].write([order_id], {"state": "sent"})
    _log(env, order_id, "RFQ sent to the vendor.")
    return {"ok": True, "message": "RFQ marked as sent.", "state": "sent"}


@object_action(MODEL, "action_confirm")
def confirm(env: Env, order_id: int) -> dict[str, Any]:
    """Confirm an RFQ and request its receipt in the same transaction."""
    order = _read(env, order_id)
    _require_state(order, ("draft", "sent"), "confirm")
    if not order.get("partner_id"):
        raise ValidationError("select a vendor before confirming")
    if not order.get("order_line"):
        raise ValidationError("add at least one order line before confirming")
    if _approval_required(env, order):
        env["purchase.order"].write(
            [order_id], {"approval_state": "waiting", "approval_note": "Awaiting manager approval."}
        )
        _log(env, order_id, "Order sent for manager approval.")
        emit(env, "purchase.order.approval_requested", {"order_id": order_id})
        return {
            "ok": True,
            "message": "Order is waiting for manager approval.",
            "state": order["state"],
            "approval_state": "waiting",
        }
    threshold = float(_settings(env).get("approval_threshold") or 0)
    if threshold > 0:
        env["purchase.order"].write(
            [order_id],
            {
                "approval_state": "approved",
                "approved_by": env.uid,
                "approved_date": dt.datetime.now(dt.UTC),
                "approval_note": "Approved on confirmation.",
            },
        )
    vendor = order["partner_id"]
    company = order.get("company_id") or {}
    lead = max((line.get("lead_time") or 0 for line in order["order_line"]), default=0)
    picking_id = create_receipt(
        env,
        origin=order["name"],
        partner_id=vendor["id"],
        company_id=company.get("id") if isinstance(company, dict) else company,
        lines=_receipt_lines(order),
        scheduled_date=dt.date.today() + dt.timedelta(days=lead),
    )
    env.with_context(allow_confirmed=True)["purchase.order"].write(
        [order_id], {"state": "purchase", "date_order": dt.datetime.now(dt.UTC)}
    )
    _log(env, order_id, "Purchase order confirmed. Receipt requested.")
    emit(
        env,
        "purchase.order.confirmed",
        {
            "order_id": order_id,
            "partner_id": vendor["id"],
            "company_id": company.get("id") if isinstance(company, dict) else company,
            "picking_id": picking_id,
        },
    )
    return {"ok": True, "message": "Purchase order confirmed.", "state": "purchase"}


@object_action(MODEL, "action_cancel")
def cancel(env: Env, order_id: int) -> dict[str, Any]:
    order = _read(env, order_id)
    _require_state(order, ("draft", "sent", "purchase"), "cancel")
    cancelled = cancel_receipts(env, origin=order["name"])
    env["purchase.order"].write([order_id], {"state": "cancel"})
    _log(env, order_id, "Purchase order cancelled.")
    emit(env, "purchase.order.cancelled", {"order_id": order_id})
    return {
        "ok": True,
        "message": "Purchase order cancelled.",
        "state": "cancel",
        "pickings_cancelled": cancelled,
    }


def recompute_receipt_status(env: Env, order_ids: list[int]) -> None:
    """Derive the stub receipt status from linked picking states."""
    if not order_ids:
        return
    safe = env.with_context(skip_totals=True)
    for order in safe["purchase.order"].read(order_ids):
        pickings = safe["inventory.picking"].search([("origin", "=", order["name"])])
        rows = safe["inventory.picking"].read(pickings)
        if not rows:
            status = "nothing"
        elif all(row["state"] == "done" for row in rows):
            status = "full"
        else:
            status = "partial"
        safe["purchase.order"].write([order["id"]], {"receipt_status": status})


@object_action(MODEL, "action_create_bill")
def create_bill(env: Env, order_id: int):
    from .billing import create_bill as build

    return build(env, order_id)


@object_action(MODEL, "action_lock")
def lock(env: Env, order_id: int):
    from .billing import lock as change

    return change(env, order_id, locked=True)


@object_action(MODEL, "action_unlock")
def unlock(env: Env, order_id: int):
    from .billing import lock as change

    return change(env, order_id, locked=False)


@object_action(MODEL, "action_approve")
def approve(env: Env, order_id: int) -> dict[str, Any]:
    """Approve a waiting order as a purchase manager, then confirm it."""
    if not _is_manager(env):
        raise ValidationError("only a purchase manager can approve this order")
    order = _read(env, order_id)
    _require_state(order, ("draft", "sent"), "approve")
    if order.get("approval_state") != "waiting":
        raise ValidationError("this order is not waiting for approval")
    env["purchase.order"].write(
        [order_id],
        {
            "approval_state": "approved",
            "approved_by": env.uid,
            "approved_date": dt.datetime.now(dt.UTC),
            "approval_note": "Approved by manager.",
        },
    )
    _log(env, order_id, "Order approved by a purchase manager.")
    emit(env, "purchase.order.approved", {"order_id": order_id})
    return confirm(env, order_id)


@object_action(MODEL, "action_reject")
def reject(env: Env, order_id: int) -> dict[str, Any]:
    """Reject a waiting order without confirming it."""
    if not _is_manager(env):
        raise ValidationError("only a purchase manager can reject this order")
    order = _read(env, order_id)
    if order.get("approval_state") != "waiting":
        raise ValidationError("this order is not waiting for approval")
    env["purchase.order"].write(
        [order_id],
        {"approval_state": "rejected", "approval_note": "Rejected by manager."},
    )
    _log(env, order_id, "Order rejected by a purchase manager.")
    return {
        "ok": True,
        "message": "Order rejected.",
        "approval_state": "rejected",
    }
