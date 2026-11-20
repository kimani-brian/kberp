"""Payment registration, allocation, reconciliation and credit notes."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from ....services.events import emit
from . import posting

INVOICE_TYPES = {"out_invoice", "in_invoice"}
EPS = Decimal("0.0001")


def _number(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def _settings(env: Env, company_id: int | None) -> dict[str, Any]:
    domain = [("company_id", "=", int(company_id))] if company_id else []
    ids = env["accounting.settings"].search(domain, limit=1)
    if not ids:
        ids = env["accounting.settings"].search([], limit=1)
    return env["accounting.settings"].read([ids[0]])[0] if ids else {}


def _account_id(account: Any) -> int | None:
    if not account:
        return None
    return account["id"] if isinstance(account, dict) else int(account)


def recompute_invoice(env: Env, move_ids: list[int]) -> None:
    """Refresh residual and payment state from posted payments and refunds."""
    if not move_ids:
        return
    safe_env = env.with_context(skip_totals=True, allow_posting=True)
    model = safe_env["accounting.move"]
    line_model = safe_env["accounting.payment_line"]
    for move in model.read(move_ids):
        allocations = line_model.read(line_model.search([("move_id", "=", move["id"])]))
        paid = sum(
            (
                _number(line["amount"])
                for line in allocations
                if (line.get("payment_id") or {}).get("id")
                and safe_env["accounting.payment"].read([line["payment_id"]["id"]])[0]["state"]
                == "posted"
            ),
            Decimal(0),
        )
        refund_ids = model.search(
            [
                ("origin", "=", move["name"]),
                ("move_type", "=", "out_refund"),
                ("state", "=", "posted"),
            ]
        )
        credited = sum(
            (_number(row["amount_total"]) for row in model.read(refund_ids)), Decimal(0)
        )
        residual = _number(move["amount_total"]) - paid + credited
        if residual <= EPS and (paid > 0 or credited < 0):
            state = "reversed" if credited < 0 else "paid"
        elif paid > 0 or credited < 0:
            state = "partial"
        else:
            state = "not paid"
        model.write(
            [move["id"]], {"amount_residual": residual, "payment_state": state}
        )


def register_payment(
    env: Env,
    move_id: int | None = None,
    *,
    amount: Decimal | float | None = None,
    journal_id: int,
    allocations: list[tuple[int, Decimal | float]] | None = None,
    date: dt.date | None = None,
    method: str = "bank",
    memo: str = "",
) -> dict[str, Any]:
    """Register one payment and allocate it over one or more invoices.

    Preconditions: every invoice is posted, belongs to the same partner and
    each allocated amount fits its residual. Side effects: a posted payment,
    its allocations and one balanced bank move.
    """
    if allocations is None:
        if move_id is None or amount is None:
            raise ValidationError("an invoice and an amount are required")
        allocations = [(move_id, amount)]
    if not allocations:
        raise ValidationError("a payment needs at least one allocation")
    invoice_ids = [int(row[0]) for row in allocations]
    rows = env["accounting.move"].read(invoice_ids)
    if len(rows) != len(invoice_ids):
        raise ValidationError("invoice not found")
    for invoice in rows:
        if invoice["state"] != "posted" or invoice["move_type"] not in INVOICE_TYPES:
            raise ValidationError("only a posted invoice or bill can be paid")
    partners = {invoice["partner_id"]["id"] for invoice in rows}
    if len(partners) != 1:
        raise ValidationError("one payment can only pay one partner")
    recompute_invoice(env, invoice_ids)
    current = {
        row["id"]: _number(row["amount_residual"])
        for row in env["accounting.move"].read(invoice_ids)
    }
    for invoice_id, allocated in allocations:
        value = _number(allocated)
        if value <= 0:
            raise ValidationError("payment amount must be positive")
        if value > current[int(invoice_id)] + EPS:
            raise ValidationError(
                f"payment of {value:,.2f} exceeds the outstanding "
                f"{current[int(invoice_id)]:,.2f}"
            )
    total = sum((_number(allocated) for _, allocated in allocations), Decimal(0))
    invoice = rows[0]
    company_id = _account_id(invoice.get("company_id"))
    invoice_rate = _number(invoice.get("currency_rate") or 1) or Decimal(1)
    currency_id = _account_id(invoice.get("currency_id"))
    payment_rate = _number(_settings(env, company_id).get("rate") or 1) or Decimal(1)
    if currency_id:
        currency = env["core.currency"].read([currency_id])
        if currency and currency[0].get("rate"):
            payment_rate = Decimal(1) / _number(currency[0]["rate"])
    sequence_model: Any = env["core.ir_sequence"]
    number = sequence_model.next_code("accounting.seq_payment")
    payment_id = env["accounting.payment"].create(
        {
            "name": number,
            "payment_type": "inbound"
            if invoice["move_type"] == "out_invoice"
            else "outbound",
            "partner_id": invoice["partner_id"]["id"],
            "journal_id": journal_id,
            "amount": total,
            "amount_company": total * payment_rate,
            "currency_id": currency_id,
            "currency_rate": payment_rate,
            "date": date or dt.date.today(),
            "method": method,
            "memo": memo,
            "state": "draft",
            "company_id": company_id,
            "payment_line_ids": [
                {"move_id": int(row_id), "amount": _number(value)}
                for row_id, value in allocations
            ],
        }
    )
    journal = env["accounting.journal"].read([journal_id])[0]
    settings = _settings(env, company_id)
    bank_id = _account_id(journal.get("default_account_id")) or _account_id(
        settings.get("bank_account_id")
    )
    partner_account = (
        settings.get("receivable_account_id")
        if invoice["move_type"] == "out_invoice"
        else settings.get("payable_account_id")
    )
    receivable_id = _account_id(partner_account)
    if not bank_id or not receivable_id:
        raise ValidationError("bank or receivable account is not configured")
    company_amount = total * payment_rate
    booked_amount = total * invoice_rate
    difference = company_amount - booked_amount
    inbound = invoice["move_type"] == "out_invoice"
    lines = [
        {
            "account_id": bank_id,
            "name": "Bank" if inbound else "Cash out",
            "debit": company_amount if inbound else Decimal(0),
            "credit": Decimal(0) if inbound else company_amount,
            "kind": "manual",
        },
        {
            "account_id": receivable_id,
            "name": "Invoice payment",
            "debit": Decimal(0) if inbound else booked_amount,
            "credit": booked_amount if inbound else Decimal(0),
            "kind": "manual",
        },
    ]
    if abs(difference) > EPS:
        exchange_id = _account_id(settings.get("exchange_account_id"))
        if not exchange_id:
            raise ValidationError("exchange difference account is not configured")
        lines.append(
            {
                "account_id": exchange_id,
                "name": "Exchange difference",
                "debit": Decimal(0) if difference > 0 else -difference,
                "credit": difference if difference > 0 else Decimal(0),
                "kind": "manual",
            }
        )
    payment_move_id = env["accounting.move"].create(
        {
            "move_type": "entry",
            "journal_id": journal_id,
            "date": date or dt.date.today(),
            "company_id": company_id,
            "currency_id": currency_id,
            "currency_rate": payment_rate,
            "origin": number,
            "note": memo,
            "line_ids": lines,
        }
    )
    posting.post(env, payment_move_id)
    env["accounting.payment"].write([payment_id], {"state": "posted"})
    recompute_invoice(env, invoice_ids)
    emit(
        env,
        "accounting.payment.registered",
        {
            "payment_id": payment_id,
            "invoice_ids": invoice_ids,
            "partner_id": invoice["partner_id"]["id"],
            "company_id": company_id,
        },
    )
    return {
        "ok": True,
        "message": f"Payment {number} registered.",
        "payment_id": payment_id,
        "state": "posted",
    }


def create_credit_note(env: Env, invoice_id: int) -> dict[str, Any]:
    """Create a draft credit note with the invoice lines pre-filled."""
    from .api import create_invoice

    rows = env["accounting.move"].read([invoice_id])
    if not rows:
        raise ValidationError("invoice not found")
    invoice = rows[0]
    if invoice["state"] != "posted" or invoice["move_type"] != "out_invoice":
        raise ValidationError("only a posted customer invoice can have a credit note")
    lines = []
    for line in invoice.get("line_ids", []):
        if line["kind"] != "product":
            continue
        lines.append(
            {
                "product_id": (line.get("product_id") or {}).get("id"),
                "name": line["name"],
                "qty": line["qty"],
                "price_unit": -_number(line["price_unit"]),
                "tax_ids": [tax["id"] for tax in line.get("tax_ids") or []],
            }
        )
    if not lines:
        raise ValidationError("the invoice has no product lines to credit")
    credit_id = create_invoice(
        env,
        partner_id=invoice["partner_id"]["id"],
        company_id=_account_id(invoice.get("company_id")),
        origin=invoice["name"],
        lines=lines,
        journal_code="SAL",
        currency_id=_account_id(invoice.get("currency_id")),
        note=invoice.get("note") or "",
        move_type="out_refund",
    )
    return {
        "ok": True,
        "message": "Draft credit note created.",
        "credit_note_id": credit_id,
    }


def cancel_payment(env: Env, payment_id: int) -> dict[str, Any]:
    """Cancel a payment and release its allocation from the invoice."""
    rows = env["accounting.payment"].read([payment_id])
    if not rows:
        raise ValidationError("payment not found")
    payment = rows[0]
    if payment["state"] == "cancel":
        raise ValidationError("payment is already cancelled")
    env["accounting.payment"].write([payment_id], {"state": "cancel"})
    line_ids = [row["id"] for row in payment["payment_line_ids"]]
    invoice_ids = [
        line["move_id"]["id"]
        for line in env["accounting.payment_line"].read(line_ids)
        if line.get("move_id")
    ]
    recompute_invoice(env, invoice_ids)
    return {"ok": True, "message": "Payment cancelled.", "state": "cancel"}
