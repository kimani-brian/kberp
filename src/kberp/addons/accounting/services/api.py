"""Public accounting API used by the commercial modules and the ledger."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ....orm.model import ValidationError

CENT = Decimal("0.01")


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def compute_taxes(
    env,
    tax_ids: list[int],
    base_amount: Decimal,
    *,
    company_id: int | None = None,
    price_include: bool = False,
    rounding: str = "line",
    quantity: float | Decimal = 1,
) -> tuple[list[dict[str, Any]], Decimal]:
    """Work out one entry per tax repartition and their total.

    Preconditions: `tax_ids` are active taxes and `base_amount` is the amount
    after discounts. Side effects: none. Percentage rates are in percent, fixed
    rates are charged per unit. Included taxes are extracted from the base.
    """
    if not tax_ids or base_amount == 0:
        return [], Decimal(0)
    taxes = env["accounting.tax"].read([int(tax_id) for tax_id in tax_ids])
    lines: list[dict[str, Any]] = []
    total = Decimal(0)
    for tax in taxes:
        if company_id and tax.get("company_id") and tax["company_id"]["id"] != company_id:
            continue
        base = Decimal(str(base_amount))
        rate = Decimal(str(tax["amount"] or 0))
        units = Decimal(str(quantity or 1))
        if tax.get("amount_type") == "fixed":
            gross = rate * units
            amount = min(gross, base) if tax.get("price_include") else gross
        else:
            factor = rate / Decimal(100)
            if tax.get("price_include") or price_include:
                amount = base - base / (Decimal(1) + factor)
            else:
                amount = base * factor
        repartitions = tax.get("repartition_ids") or []
        if not repartitions:
            entry = {
                "tax_id": tax["id"],
                "name": tax["name"],
                "amount": _round(amount) if rounding == "line" else amount,
                "account_id": None,
                "group_id": (tax.get("group_id") or {}).get("id"),
            }
            lines.append(entry)
            total += entry["amount"]
            continue
        for repartition in repartitions:
            share = amount * Decimal(str(repartition.get("factor") or 0))
            account = repartition.get("account_id") or {}
            entry = {
                "tax_id": tax["id"],
                "name": repartition.get("label") or tax["name"],
                "amount": _round(share) if rounding == "line" else share,
                "account_id": account.get("id") if isinstance(account, dict) else account,
                "group_id": (tax.get("group_id") or {}).get("id"),
            }
            lines.append(entry)
            total += entry["amount"]
    return lines, _round(total)


def count_documents(env, partner_id: int, company_id: int | None = None) -> int:
    """Number of accounting documents linked to a partner (smart-button API)."""
    domain: list[Any] = [("partner_id", "=", partner_id)]
    if company_id:
        domain.append(("company_id", "=", company_id))
    return env["accounting.move"].search_count(domain)


def create_invoice(
    env,
    *,
    partner_id: int,
    company_id: int | None,
    origin: str,
    lines: list[dict[str, Any]],
    journal_code: str = "SAL",
    currency_id: int | None = None,
    note: str = "",
    move_type: str = "out_invoice",
) -> int:
    """Create a draft customer invoice from commercial document lines.

    Preconditions: `lines` carry product_id, name, qty, price_unit and tax_ids.
    Side effects: none beyond the draft move; the caller posts it if required.
    """
    journal_ids = env["accounting.journal"].search(
        [("code", "=", journal_code)], limit=1
    )
    if not journal_ids:
        raise ValidationError(f"journal {journal_code} is not configured")
    partner = env["core.partner"].read([int(partner_id)])
    country = (partner[0].get("country_id") or {}).get("id") if partner else None
    position = None
    if country:
        position_ids = env["accounting.fiscal_position"].search(
            [("country_id", "=", int(country))], limit=1
        )
        if position_ids:
            position = env["accounting.fiscal_position"].read([position_ids[0]])[0]
    mapped_lines = []
    for line in lines:
        line = dict(line)
        if position:
            source_tax = (position.get("source_tax_id") or {}).get("id")
            dest_tax = (position.get("dest_tax_id") or {}).get("id")
            if source_tax and dest_tax:
                line["tax_ids"] = [
                    dest_tax if int(tax) == int(source_tax) else tax
                    for tax in line.get("tax_ids") or []
                ]
            source_account = (position.get("source_account_id") or {}).get("id")
            dest_account = (position.get("dest_account_id") or {}).get("id")
            if source_account and dest_account and line.get("account_id") == source_account:
                line["account_id"] = dest_account
        mapped_lines.append(line)

    rate = 1.0
    if currency_id and company_id:
        company = env["core.company"].read([int(company_id)])
        company_currency = (company[0].get("currency_id") or {}).get("id") if company else None
        if company_currency and int(company_currency) != int(currency_id):
            currency = env["core.currency"].read([int(currency_id)])
            if currency and currency[0].get("rate"):
                rate = float(1) / float(currency[0]["rate"])
    return env["accounting.move"].create(
        {
            "move_type": move_type,
            "partner_id": partner_id,
            "journal_id": journal_ids[0],
            "date": dt.date.today(),
            "company_id": company_id,
            "currency_id": currency_id,
            "currency_rate": rate,
            "origin": origin,
            "note": note,
            "line_ids": [
                {
                    "product_id": line.get("product_id"),
                    "account_id": line.get("account_id"),
                    "name": line.get("name") or "Product",
                    "qty": line.get("qty", 0),
                    "price_unit": line.get("price_unit", 0),
                    "tax_ids": line.get("tax_ids") or [],
                    "kind": "product",
                }
                for line in mapped_lines
                if line.get("product_id")
            ],
        }
    )


def create_bill(
    env,
    *,
    partner_id: int,
    company_id: int | None,
    origin: str,
    lines: list[dict[str, Any]],
    **kwargs: Any,
) -> int:
    """Create a draft vendor bill from purchase document lines."""
    kwargs.setdefault("journal_code", "PUR")
    return create_invoice(
        env,
        partner_id=partner_id,
        company_id=company_id,
        origin=origin,
        lines=lines,
        move_type="in_invoice",
        **kwargs,
    )
