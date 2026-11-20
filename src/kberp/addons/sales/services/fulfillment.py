"""Delivery, invoicing and lock state for confirmed sales orders."""

from __future__ import annotations

from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from ...accounting.services.api import create_invoice as new_invoice


def _ids(value: Any) -> list[int]:
    if not value:
        return []
    if isinstance(value, dict):
        return [int(value["id"])]
    return [int(item) for item in value]


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def recompute(env: Env, order_ids: list[int]) -> None:
    """Rebuild delivered and invoiced quantities from source documents.

    Preconditions: none. Side effects: writes stored quantities and status on
    orders and lines. Recomputing from the documents makes the inventory and
    accounting event handlers idempotent.
    """
    if not order_ids:
        return
    safe_env = env.with_context(skip_totals=True, allow_locked=True)
    order_model = safe_env["sales.order"]
    line_model = safe_env["sales.order_line"]
    picking_model = safe_env["inventory.picking"]
    stock_move_model = safe_env["inventory.move"]
    invoice_model = safe_env["accounting.move"]
    invoice_line_model = safe_env["accounting.move_line"]

    for order in order_model.read(order_ids):
        lines = line_model.read([row["id"] for row in order.get("order_line", [])])
        pickings = picking_model.search(
            [("origin", "=", order["name"]), ("state", "=", "done")]
        )
        invoices = invoice_model.search(
            [
                ("origin", "=", order["name"]),
                ("move_type", "=", "out_invoice"),
                ("state", "in", ["draft", "posted"]),
            ]
        )
        stock_moves = (
            stock_move_model.read(stock_move_model.search([("picking_id", "in", pickings)]))
            if pickings
            else []
        )
        invoice_lines = (
            invoice_line_model.read(
                invoice_line_model.search([("move_id", "in", invoices), ("kind", "=", "product")])
            )
            if invoices
            else []
        )
        total_delivered = 0.0
        total_invoiced = 0.0
        over_invoiced = False
        for line in lines:
            product_id = (line.get("product_id") or {}).get("id")
            delivered = sum(
                _number(move["done_qty"])
                for move in stock_moves
                if (move.get("product_id") or {}).get("id") == product_id
            )
            invoiced = sum(
                _number(item["qty"])
                for item in invoice_lines
                if (item.get("product_id") or {}).get("id") == product_id
            )
            total_delivered += delivered
            total_invoiced += invoiced
            if invoiced > _number(line["qty"]) + 0.0001:
                over_invoiced = True
            line_model.write(
                [line["id"]], {"qty_delivered": delivered, "qty_invoiced": invoiced}
            )

        policy = order.get("invoice_policy") or "ordered"
        target_delivered = total_delivered if policy == "delivered" else sum(
            _number(line["qty"]) for line in lines
        )
        if over_invoiced:
            status = "upselling"
        elif target_delivered > 0 and total_invoiced >= target_delivered - 0.0001:
            status = "fully invoiced"
        elif total_invoiced > 0 or total_delivered > 0:
            status = "to invoice"
        else:
            status = "nothing"
        order_model.write(
            [order["id"]],
            {
                "qty_delivered": total_delivered,
                "qty_invoiced": total_invoiced,
                "invoice_status": status,
            },
        )


def create_invoice(env: Env, order_id: int) -> dict[str, Any]:
    """Create one draft invoice for the order's remaining invoiceable quantity."""
    order = env["sales.order"].read([order_id])
    if not order:
        raise ValidationError("order not found")
    row = order[0]
    if row["state"] != "sale":
        raise ValidationError("only a confirmed order can be invoiced")
    if row["locked"]:
        raise ValidationError("a locked order cannot be invoiced")
    lines = env["sales.order_line"].read([line["id"] for line in row.get("order_line", [])])
    policy = row.get("invoice_policy") or "ordered"
    invoice_lines: list[dict[str, Any]] = []
    for line in lines:
        ordered = _number(line["qty"])
        delivered = _number(line["qty_delivered"])
        invoiced = _number(line["qty_invoiced"])
        target = delivered if policy == "delivered" else ordered
        remaining = target - invoiced
        if remaining <= 0.0001:
            continue
        if remaining > ordered - invoiced + 0.0001 and policy == "delivered":
            raise ValidationError(f"cannot invoice more than ordered for {line['name']}")
        invoice_lines.append(
            {
                "product_id": (line.get("product_id") or {}).get("id"),
                "name": line["name"],
                "qty": remaining,
                "price_unit": line["price_unit"],
                "tax_ids": [tax["id"] for tax in line.get("tax_ids") or []],
            }
        )
    if not invoice_lines:
        raise ValidationError("there is nothing left to invoice on this order")
    invoice_id = new_invoice(
        env,
        partner_id=row["partner_id"]["id"],
        company_id=(row.get("company_id") or {}).get("id"),
        origin=row["name"],
        lines=invoice_lines,
        currency_id=(row.get("currency_id") or {}).get("id"),
        note=row.get("note") or "",
    )
    recompute(env, [order_id])
    return {
        "ok": True,
        "message": "Draft invoice created.",
        "invoice_id": invoice_id,
    }


def lock(env: Env, order_id: int, *, locked: bool = True) -> dict[str, Any]:
    """Lock or unlock a confirmed order. Locked orders reject field writes."""
    order = env["sales.order"].read([order_id])
    if not order:
        raise ValidationError("order not found")
    if order[0]["state"] != "sale":
        raise ValidationError("only a confirmed order can be locked")
    env.with_context(allow_locked=True)["sales.order"].write(
        [order_id], {"locked": locked}
    )
    return {
        "ok": True,
        "message": "Order locked." if locked else "Order unlocked.",
        "locked": locked,
    }
