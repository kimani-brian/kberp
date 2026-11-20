"""Purchase analysis snapshots."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....env import Env
from ....orm.model import ValidationError


def run(env: Env, analysis_id: int) -> dict[str, Any]:
    """Rebuild an analysis from confirmed purchase order lines in its dates."""
    rows = env["purchase.analysis"].read([analysis_id])
    if not rows:
        raise ValidationError("analysis not found")
    analysis = rows[0]
    date_from = analysis.get("date_from") or dt.date.min
    date_to = analysis.get("date_to") or dt.date.max
    if date_from > date_to:
        raise ValidationError("the start date cannot be after the end date")
    order_ids = env["purchase.order"].search([("state", "=", "purchase")])
    orders = {
        row["id"]: row
        for row in env["purchase.order"].read(order_ids)
        if row.get("date_order") and date_from <= row["date_order"].date() <= date_to
    }
    group_by = analysis.get("group_by") or "vendor"
    buckets: dict[str, dict[str, Any]] = {}
    line_ids = env["purchase.order_line"].search([("order_id", "in", list(orders))])
    for line in env["purchase.order_line"].read(line_ids):
        order = orders.get((line.get("order_id") or {}).get("id"))
        if not order:
            continue
        if group_by == "vendor":
            partner = order.get("partner_id") or {}
            key = partner.get("name") or "No vendor"
        elif group_by == "category":
            product_id = (line.get("product_id") or {}).get("id")
            product = env["core.product_template"].read([product_id]) if product_id else []
            category = (product[0].get("category_id") or {}) if product else {}
            key = category.get("name") or "No category"
        else:
            key = line.get("name") or "No product"
        bucket = buckets.setdefault(key, {"qty": 0.0, "amount": 0.0})
        bucket["qty"] += float(line.get("qty") or 0)
        bucket["amount"] += float(line.get("subtotal") or 0)
    line_model = env["purchase.analysis_line"]
    line_model.unlink(
        [row["id"] for row in analysis.get("line_ids", [])]
    )
    for index, (label, bucket) in enumerate(
        sorted(buckets.items(), key=lambda item: -item[1]["amount"])
    ):
        line_model.create(
            {
                "analysis_id": analysis_id,
                "sequence": (index + 1) * 10,
                "label": label,
                "qty": bucket["qty"],
                "amount": bucket["amount"],
            }
        )
    env["purchase.analysis"].write([analysis_id], {"state": "computed"})
    return {
        "ok": True,
        "message": f"Analysis rebuilt with {len(buckets)} rows.",
        "state": "computed",
    }
