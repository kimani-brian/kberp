"""Receipt feedback, bill creation and three-way match quantities."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from ...accounting.services.api import create_bill as new_bill

EPS = Decimal("0.0001")


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _product_id(value: Any) -> int | None:
    if not value:
        return None
    return value["id"] if isinstance(value, dict) else int(value)


def recompute(env: Env, order_ids: list[int]) -> None:
    """Rebuild received and billed quantities from source documents.

    Idempotent by construction: both quantities are recomputed from scratch, so
    repeated inventory or accounting events cannot double count.
    """
    if not order_ids:
        return
    safe = env.with_context(skip_totals=True, allow_locked=True)
    orders = safe["purchase.order"]
    lines_model = safe["purchase.order_line"]
    for order in orders.read(order_ids):
        lines = lines_model.read([row["id"] for row in order.get("order_line", [])])
        base = order["name"]
        picking_ids = safe["inventory.picking"].search(
            [
                "|",
                ("origin", "=", base),
                ("origin", "like", f"{base}-BO%"),
                ("state", "=", "done"),
            ]
        )
        moves = (
            safe["inventory.move"].read(
                safe["inventory.move"].search([("picking_id", "in", picking_ids)])
            )
            if picking_ids
            else []
        )
        bill_ids = safe["accounting.move"].search(
            [
                ("origin", "=", order["name"]),
                ("move_type", "=", "in_invoice"),
                ("state", "in", ["draft", "posted"]),
            ]
        )
        bill_lines = (
            safe["accounting.move_line"].read(
                safe["accounting.move_line"].search(
                    [("move_id", "in", bill_ids), ("kind", "=", "product")]
                )
            )
            if bill_ids
            else []
        )
        total_received = 0.0
        total_billed = 0.0
        for line in lines:
            product = _product_id(line.get("product_id"))
            received = sum(_number(move["done_qty"]) for move in moves if _product_id(move.get("product_id")) == product)
            billed = sum(_number(item["qty"]) for item in bill_lines if _product_id(item.get("product_id")) == product)
            total_received += received
            total_billed += billed
            lines_model.write(
                [line["id"]], {"qty_received": received, "qty_billed": billed}
            )
        ordered_total = sum(_number(line["qty"]) for line in lines)
        if ordered_total and total_received >= ordered_total - 0.0001:
            receipt_status = "full"
        elif total_received > 0:
            receipt_status = "partial"
        else:
            receipt_status = "nothing"
        if ordered_total and total_billed >= ordered_total - 0.0001:
            invoice_status = "full"
        elif total_billed > 0:
            invoice_status = "waiting"
        else:
            invoice_status = "nothing"
        orders.write(
            [order["id"]],
            {
                "qty_received": total_received,
                "qty_billed": total_billed,
                "receipt_status": receipt_status,
                "invoice_status": invoice_status,
            },
        )


def billable_qty(line: dict[str, Any], policy: str) -> float:
    """Quantity still billable for one order line under the control policy."""
    ordered = _number(line["qty"])
    billed = _number(line.get("qty_billed"))
    if policy == "received":
        target = _number(line.get("qty_received"))
    else:
        target = ordered
    return max(min(target, ordered) - billed, 0)


def create_bill(env: Env, order_id: int) -> dict[str, Any]:
    """Create one draft vendor bill for the currently billable quantities."""
    rows = env["purchase.order"].read([order_id])
    if not rows:
        raise ValidationError("purchase order not found")
    order = rows[0]
    if order["state"] != "purchase":
        raise ValidationError("only a confirmed purchase order can be billed")
    if order["locked"]:
        raise ValidationError("a locked purchase order cannot be billed")
    policy = order.get("bill_control") or "ordered"
    lines = env["purchase.order_line"].read([row["id"] for row in order.get("order_line", [])])
    if policy == "received" and all(
        _number(line.get("qty_received")) <= 0.0001 for line in lines
    ):
        raise ValidationError(
            "nothing received yet for this purchase order, so it cannot be billed"
        )
    bill_lines = []
    for line in lines:
        remaining = billable_qty(line, policy)
        if remaining <= 0.0001:
            continue
        if policy == "received" and _number(line.get("qty_received")) <= 0.0001:
            raise ValidationError(
                f"nothing received yet for {line['name']}, so it cannot be billed"
            )
        bill_lines.append(
            {
                "product_id": _product_id(line.get("product_id")),
                "name": line["name"],
                "qty": remaining,
                "price_unit": line["price_unit"],
                "tax_ids": [tax["id"] for tax in line.get("tax_ids") or []],
            }
        )
    if not bill_lines:
        raise ValidationError("there is nothing left to bill on this order")
    bill_id = new_bill(
        env,
        partner_id=order["partner_id"]["id"],
        company_id=(order.get("company_id") or {}).get("id"),
        origin=order["name"],
        lines=bill_lines,
        currency_id=(order.get("currency_id") or {}).get("id"),
        note=order.get("note") or "",
    )
    recompute(env, [order_id])
    return {
        "ok": True,
        "message": "Draft vendor bill created.",
        "bill_id": bill_id,
    }


def lock(env: Env, order_id: int, *, locked: bool = True) -> dict[str, Any]:
    """Lock or unlock a confirmed purchase order."""
    rows = env["purchase.order"].read([order_id])
    if not rows:
        raise ValidationError("purchase order not found")
    if rows[0]["state"] != "purchase":
        raise ValidationError("only a confirmed purchase order can be locked")
    env.with_context(allow_locked=True)["purchase.order"].write(
        [order_id], {"locked": locked}
    )
    return {
        "ok": True,
        "message": "Purchase order locked." if locked else "Purchase order unlocked.",
        "locked": locked,
    }
