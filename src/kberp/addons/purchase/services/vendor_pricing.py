"""Vendor price selection for purchase documents."""

from __future__ import annotations

import datetime as dt
from typing import Any


def vendor_price(
    env,
    *,
    partner_id: int,
    product_id: int,
    qty: float = 1,
    currency_id: int | None = None,
    date: dt.date | None = None,
) -> dict[str, Any] | None:
    """Return the best vendor price for a product and quantity.

    Precedence: the largest minimum quantity that the line reaches, then a
    matching currency, then the most recent valid record. Dates are inclusive.
    """
    model = env["purchase.vendor_price"]
    ids = model.search(
        [
            ("partner_id", "=", partner_id),
            ("product_id", "=", product_id),
            ("active", "=", True),
            ("min_qty", "<=", qty),
        ],
        order="-min_qty, -id",
    )
    if not ids:
        return None
    today = date or dt.date.today()
    rows = model.read(ids)
    for row in rows:
        if row.get("date_start") and today < row["date_start"]:
            continue
        if row.get("date_end") and today > row["date_end"]:
            continue
        row_currency = row.get("currency_id") or {}
        if currency_id and row_currency and row_currency["id"] != currency_id:
            continue
        return {
            "price": row["price"],
            "currency_id": (row.get("currency_id") or {}).get("id"),
            "lead_time": row.get("lead_time") or 0,
            "name": row["name"],
        }
    return None
