"""Public purchase API used by Inventory replenishment."""

from __future__ import annotations

from typing import Any

from ....orm.model import ValidationError


def preferred_vendor(env, product_id: int) -> int | None:
    """Return the vendor with the best active price for a product."""
    prices = env["purchase.vendor_price"]
    ids = prices.search([("product_id", "=", product_id), ("active", "=", True)], order="price, id")
    if not ids:
        return None
    row = prices.read([ids[0]])[0]
    partner = row.get("partner_id") or {}
    return partner.get("id") if isinstance(partner, dict) else partner


def create_rfq(
    env,
    *,
    partner_id: int,
    company_id: int | None,
    lines: list[dict[str, Any]],
    origin: str,
    currency_id: int | None = None,
) -> int:
    """Create a draft RFQ from another module through this public API."""
    if not partner_id or not lines:
        raise ValidationError("an RFQ needs a vendor and at least one line")
    existing = env["purchase.order"].search([("origin", "=", origin)], limit=1)
    if existing:
        return existing[0]
    return env["purchase.order"].create(
        {
            "partner_id": partner_id,
            "company_id": company_id,
            "currency_id": currency_id,
            "origin": origin,
            "order_line": [
                {
                    "product_id": line.get("product_id"),
                    "name": line.get("name") or "Replenishment",
                    "qty": line.get("qty", 0),
                }
                for line in lines
                if line.get("product_id")
            ],
        }
    )
