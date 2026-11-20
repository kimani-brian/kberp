"""Vendor performance and purchase suggestions from history."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....env import Env


def vendor_on_time_rate(env: Env, partner_id: int) -> dict[str, Any]:
    """Share of completed receipts that arrived on or before the due date."""
    orders = env["purchase.order"].search(
        [("partner_id", "=", partner_id), ("state", "=", "purchase")]
    )
    rows = env["purchase.order"].read(orders)
    names = {row["name"] for row in rows}
    scheduled = {
        row["name"]: row.get("expected_date")
        for row in rows
        if row.get("expected_date")
    }
    if not names:
        return {"orders": 0, "receipts": 0, "on_time": 0, "rate": 0.0}
    picking_ids = env["inventory.picking"].search(
        [("origin", "in", list(names)), ("picking_type", "=", "in"), ("state", "=", "done")]
    )
    on_time = 0
    total = 0
    for picking in env["inventory.picking"].read(picking_ids):
        total += 1
        due = scheduled.get(picking["origin"])
        written = picking.get("write_date")
        if due and written:
            if written.date() <= due:
                on_time += 1
        else:
            on_time += 1
    rate = round(on_time / total * 100, 1) if total else 0.0
    return {"orders": len(rows), "receipts": total, "on_time": on_time, "rate": rate}


def suggestions(env: Env, product_id: int) -> list[dict[str, Any]]:
    """The last few vendor prices for a product, newest first."""
    ids = env["purchase.order_line"].search(
        [("product_id", "=", product_id)], order="-id", limit=5
    )
    result = []
    for line in env["purchase.order_line"].read(ids):
        order_id = (line.get("order_id") or {}).get("id")
        if not order_id:
            continue
        order = env["purchase.order"].read([order_id])[0]
        if order["state"] == "cancel":
            continue
        result.append(
            {
                "order_id": order_id,
                "partner_id": (order.get("partner_id") or {}).get("id"),
                "date": order.get("date_order") or dt.date.today(),
                "qty": line.get("qty"),
                "price_unit": line.get("price_unit"),
            }
        )
    return result
