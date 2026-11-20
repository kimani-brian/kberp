"""Purchase document totals, quantised to the order currency."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ...accounting.services.api import compute_taxes


def _amount(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def recompute_totals(env, order_ids: list[int]) -> None:
    if not order_ids:
        return
    safe_env = env.with_context(skip_totals=True)
    orders = safe_env["purchase.order"].read(order_ids)
    line_model = safe_env["purchase.order_line"]
    for order in orders:
        lines = line_model.read([line["id"] for line in order.get("order_line", [])])
        untaxed = Decimal(0)
        taxes = Decimal(0)
        for line in lines:
            subtotal = _amount(line["price_unit"]) * _amount(line["qty"] or 1)
            untaxed += subtotal
            line_model.write([line["id"]], {"subtotal": subtotal})
            tax_ids = [tax["id"] for tax in line.get("tax_ids") or []]
            if tax_ids:
                _, amount = compute_taxes(
                    env, tax_ids, subtotal, company_id=(order.get("company_id") or {}).get("id")
                )
                taxes += amount
        currency_id = (order.get("currency_id") or {}).get("id")
        places = 2
        if currency_id:
            currency = env["core.currency"].read([int(currency_id)])
            if currency:
                places = int(currency[0].get("decimal_places") or 2)
        quantum = Decimal(1).scaleb(-places)
        untaxed = untaxed.quantize(quantum, rounding=ROUND_HALF_UP)
        taxes = taxes.quantize(quantum, rounding=ROUND_HALF_UP)
        safe_env["purchase.order"].write(
            [order["id"]],
            {
                "amount_untaxed": untaxed,
                "amount_tax": taxes,
                "amount_total": (untaxed + taxes).quantize(quantum),
            },
        )
