"""Quotation pricing: stored amounts follow one rule, on the server."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ...accounting.services.api import compute_taxes

CENT = Decimal("0.01")


def _amount(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    return Decimal(str(value))


def recompute_totals(env, order_ids: list[int]) -> None:
    """Recompute line subtotals, tax lines and order totals.

    Preconditions: the lines have been saved. Side effects: writes stored amount
    columns with totals disabled so the call cannot recurse. Currency rounding
    follows the order currency; the company currency is the fallback.
    """
    if not order_ids:
        return
    orders = env["sales.order"].read(order_ids)
    line_model = env["sales.order_line"]
    for order in orders:
        line_ids = [line["id"] for line in order.get("order_line", [])]
        lines = line_model.read(line_ids)
        untaxed = Decimal(0)
        by_tax: dict[int, Decimal] = {}
        tax_names: dict[int, str] = {}
        for line in lines:
            price = _amount(line.get("price_unit"))
            qty = _amount(line.get("qty"))
            discount = _amount(line.get("discount"))
            subtotal = (price * qty * (Decimal(1) - discount / Decimal(100))).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            untaxed += subtotal
            env.with_context(skip_totals=True)["sales.order_line"].write(
                [line["id"]], {"subtotal": subtotal}
            )
            for tax in line.get("tax_ids") or []:
                tax_id = int(tax["id"])
                by_tax[tax_id] = by_tax.get(tax_id, Decimal(0)) + subtotal
                tax_names[tax_id] = tax["name"]

        tax_total = Decimal(0)
        if by_tax:
            company = order.get("company_id") or {}
            for tax_id, base in by_tax.items():
                _, amount = compute_taxes(
                    env,
                    [tax_id],
                    base,
                    company_id=company.get("id") if isinstance(company, dict) else None,
                )
                tax_total += amount

        currency_id = (order.get("currency_id") or {}).get("id")
        places = 2
        if currency_id:
            currency = env["core.currency"].read([int(currency_id)])
            if currency:
                places = int(currency[0].get("decimal_places") or 2)
        quantum = Decimal(1).scaleb(-places)
        untaxed = untaxed.quantize(quantum, rounding=ROUND_HALF_UP)
        tax_total = tax_total.quantize(quantum, rounding=ROUND_HALF_UP)
        env.with_context(skip_totals=True)["sales.order"].write(
            [order["id"]],
            {
                "amount_untaxed": untaxed,
                "amount_tax": tax_total,
                "amount_total": (untaxed + tax_total).quantize(quantum),
            },
        )


def tax_lines(env, order: dict[str, Any]) -> list[dict[str, Any]]:
    """Tax breakdown for the form footer, grouped by rate."""
    grouped: dict[int, dict[str, Any]] = {}
    for line in order.get("order_line", []):
        for tax in line.get("tax_ids") or []:
            tax_id = int(tax["id"])
            entry = grouped.setdefault(
                tax_id, {"name": tax["name"], "base": Decimal(0), "amount": Decimal(0)}
            )
            entry["base"] += _amount(line.get("subtotal"))
    result = []
    for tax_id, entry in grouped.items():
        _, amount = compute_taxes(env, [tax_id], entry["base"])
        result.append({"name": entry["name"], "amount": amount})
    return result
