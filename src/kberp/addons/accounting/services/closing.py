"""Closing controls, assets, loans, deferrals, follow-ups and e-invoicing."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from . import payments, posting

EPS = Decimal("0.0001")
INVOICE_TYPES = {"out_invoice", "in_invoice", "out_refund", "in_refund"}


def _number(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def _id(value: Any) -> int | None:
    if not value:
        return None
    return value["id"] if isinstance(value, dict) else int(value)


def _read_one(env: Env, model: str, value: Any) -> dict[str, Any]:
    record_id = _id(value)
    if not record_id:
        return {}
    rows = env[model].read([record_id])
    return rows[0] if rows else {}


def _settings(env: Env, company_id: int | None = None) -> dict[str, Any]:
    domain = [("company_id", "=", int(company_id))] if company_id else []
    ids = env["accounting.settings"].search(domain, limit=1)
    if not ids:
        ids = env["accounting.settings"].search([], limit=1)
    return env["accounting.settings"].read([ids[0]])[0] if ids else {}


# -- lock dates -----------------------------------------------------------
def lock_row(env: Env, company_id: int | None = None) -> dict[str, Any]:
    domain = [("company_id", "=", int(company_id))] if company_id else []
    ids = env["accounting.lock_date"].search(domain, limit=1)
    if not ids:
        ids = env["accounting.lock_date"].search([], limit=1)
    return env["accounting.lock_date"].read([ids[0]])[0] if ids else {}


def check_locked(env: Env, move: dict[str, Any]) -> None:
    """Reject a posting or edit inside a locked period with a clear reason."""
    if move.get("state") == "posted":
        return
    date = move.get("date")
    if not date:
        return
    row = lock_row(env, _id(move.get("company_id")))
    if not row:
        return
    move_type = move.get("move_type") or "entry"
    checks: list[tuple[Any, str]] = [(row.get("date_hard"), "global")]
    if move_type in ("out_invoice", "out_refund"):
        checks.append((row.get("date_sales"), "sales"))
    if move_type in ("in_invoice", "in_refund"):
        checks.append((row.get("date_purchase"), "purchase"))
    for value, label in checks:
        if value and date <= value:
            reason = row.get("reason") or "no reason was recorded"
            raise ValidationError(
                f"{date} falls inside the {label} lock date {value}. {reason}"
            )


def secure(env: Env, move_id: int) -> dict[str, Any]:
    """Secure a posted entry so even an administrator cannot edit it."""
    rows = env["accounting.move"].read([move_id])
    if not rows:
        raise ValidationError("entry not found")
    move = rows[0]
    if move["state"] != "posted":
        raise ValidationError("only a posted entry can be secured")
    if move.get("secured"):
        return {"ok": True, "message": "Entry is already secured.", "secured": True}
    env.with_context(allow_posting=True)["accounting.move"].write(
        [move_id], {"secured": True}
    )
    posting._audit(env, move_id, "secure", "Secured against edits")
    return {"ok": True, "message": "Entry secured.", "secured": True}


# -- tax returns ----------------------------------------------------------
def compute_tax_return(env: Env, return_id: int) -> dict[str, Any]:
    """Rebuild a tax return from posted tax lines in its date range."""
    rows = env["accounting.tax_return"].read([return_id])
    if not rows:
        raise ValidationError("tax return not found")
    tax_return = rows[0]
    date_from = tax_return["date_from"]
    date_to = tax_return["date_to"]
    move_ids = env["accounting.move"].search(
        [("state", "=", "posted"), ("date", ">=", date_from), ("date", "<=", date_to)]
    )
    moves = {row["id"]: row for row in env["accounting.move"].read(move_ids)}
    line_model = env["accounting.move_line"]
    line_ids = line_model.search([("move_id", "in", list(moves))])
    buckets: dict[Any, dict[str, Any]] = {}
    for line in line_model.read(line_ids):
        move = moves[(line.get("move_id") or {}).get("id")]
        if line.get("kind") != "tax":
            continue
        tax = line.get("tax_id") or {}
        key = tax.get("id") or line.get("name")
        bucket = buckets.setdefault(
            key, {"tax_id": tax.get("id"), "label": tax.get("name") or line["name"], "base": Decimal(0), "amount": Decimal(0)}
        )
        direction = Decimal(-1) if move["move_type"] in ("in_invoice", "in_refund") else Decimal(1)
        bucket["amount"] += direction * (_number(line["credit"]) - _number(line["debit"]))
    for bucket in buckets.values():
        if not bucket["tax_id"]:
            continue
        product_lines = [
            line
            for line in line_model.read(line_ids)
            if line.get("kind") == "product"
            and any(
                (tax.get("id") if isinstance(tax, dict) else tax) == bucket["tax_id"]
                for tax in line.get("tax_ids") or []
            )
        ]
        bucket["base"] = sum(
            (_number(line.get("subtotal")) for line in product_lines), Decimal(0)
        )
    line_model_ret = env["accounting.tax_return_line"]
    line_model_ret.unlink([row["id"] for row in tax_return.get("line_ids", [])])
    total = Decimal(0)
    for label_bucket in buckets.values():
        line_model_ret.create(
            {
                "return_id": return_id,
                "tax_id": label_bucket["tax_id"],
                "label": label_bucket["label"],
                "base_amount": label_bucket["base"],
                "tax_amount": label_bucket["amount"],
            }
        )
        total += label_bucket["amount"]
    env["accounting.tax_return"].write(
        [return_id], {"state": "computed", "amount_total": total}
    )
    return {"ok": True, "message": f"Tax return computed. Tax due {total:,.2f}.", "amount_total": str(total)}


# -- assets ---------------------------------------------------------------
def compute_asset(env: Env, asset_id: int) -> dict[str, Any]:
    rows = env["accounting.asset"].read([asset_id])
    if not rows:
        raise ValidationError("asset not found")
    asset = rows[0]
    model = _read_one(env, "accounting.asset_model", asset.get("model_id"))
    months = int(model.get("duration_months") or 60)
    value = _number(asset.get("original_value"))
    if months <= 0 or value <= 0:
        raise ValidationError("an asset needs a value and a positive duration")
    line_model = env["accounting.asset_line"]
    line_model.unlink([row["id"] for row in asset.get("line_ids", [])])
    monthly = (value / months).quantize(Decimal("0.01"))
    remaining = value
    from ..models.closing import month_add

    for index in range(months):
        amount = monthly if index < months - 1 else remaining
        remaining -= amount
        line_model.create(
            {
                "asset_id": asset_id,
                "date": month_add(asset["date_start"], index + 1),
                "amount": amount,
            }
        )
    env["accounting.asset"].write([asset_id], {"state": "running"})
    return {"ok": True, "message": f"Depreciation scheduled over {months} months.", "state": "running"}


def post_depreciation(env: Env, asset_id: int) -> dict[str, Any]:
    rows = env["accounting.asset"].read([asset_id])
    if not rows:
        raise ValidationError("asset not found")
    asset = rows[0]
    model = _read_one(env, "accounting.asset_model", asset.get("model_id"))
    expense_id = _id(model.get("expense_account_id"))
    accumulated_id = _id(model.get("depreciation_account_id"))
    journal_id = _id(model.get("journal_id"))
    if not expense_id or not accumulated_id or not journal_id:
        raise ValidationError("the asset model is missing accounts or a journal")
    posted = 0
    for line in env["accounting.asset_line"].read(
        [row["id"] for row in asset.get("line_ids", [])]
    ):
        if line["state"] == "posted" or line["date"] > dt.date.today():
            continue
        entry_id = env["accounting.move"].create(
            {
                "move_type": "entry",
                "journal_id": journal_id,
                "date": line["date"],
                "company_id": _id(asset.get("company_id")),
                "origin": asset["name"],
                "note": "Depreciation",
                "line_ids": [
                    {
                        "account_id": expense_id,
                        "name": "Depreciation",
                        "debit": _number(line["amount"]),
                        "credit": Decimal(0),
                    },
                    {
                        "account_id": accumulated_id,
                        "name": "Accumulated depreciation",
                        "debit": Decimal(0),
                        "credit": _number(line["amount"]),
                    },
                ],
            }
        )
        posting.post(env, entry_id)
        env["accounting.asset_line"].write(
            [line["id"]], {"state": "posted", "move_id": entry_id}
        )
        posted += 1
    return {"ok": True, "message": f"{posted} depreciation entries posted."}


# -- loans ----------------------------------------------------------------
def compute_loan(env: Env, loan_id: int) -> dict[str, Any]:
    rows = env["accounting.loan"].read([loan_id])
    if not rows:
        raise ValidationError("loan not found")
    loan = rows[0]
    months = int(loan.get("duration_months") or 12)
    principal = _number(loan.get("amount"))
    rate = _number(loan.get("rate")) / Decimal(100) / Decimal(12)
    if months <= 0 or principal <= 0:
        raise ValidationError("a loan needs a principal and a positive duration")
    line_model = env["accounting.loan_line"]
    line_model.unlink([row["id"] for row in loan.get("line_ids", [])])
    monthly = (principal / months).quantize(Decimal("0.01"))
    remaining = principal
    from ..models.closing import month_add

    for index in range(months):
        amount = monthly if index < months - 1 else remaining
        interest = (remaining * rate).quantize(Decimal("0.01"))
        remaining -= amount
        line_model.create(
            {
                "loan_id": loan_id,
                "date": month_add(loan["date_start"], index + 1),
                "principal": amount,
                "interest": interest,
            }
        )
    env["accounting.loan"].write([loan_id], {"state": "running"})
    return {"ok": True, "message": f"Loan schedule built over {months} months.", "state": "running"}


def post_loan(env: Env, loan_id: int) -> dict[str, Any]:
    rows = env["accounting.loan"].read([loan_id])
    if not rows:
        raise ValidationError("loan not found")
    loan = rows[0]
    loan_account = _id(loan.get("loan_account_id"))
    interest_account = _id(loan.get("interest_account_id"))
    bank_account = _id(loan.get("bank_account_id"))
    journal_id = _id(loan.get("journal_id"))
    if not all((loan_account, interest_account, bank_account, journal_id)):
        raise ValidationError("the loan is missing accounts or a journal")
    posted = 0
    for line in env["accounting.loan_line"].read(
        [row["id"] for row in loan.get("line_ids", [])]
    ):
        if line["state"] == "posted" or line["date"] > dt.date.today():
            continue
        entry_id = env["accounting.move"].create(
            {
                "move_type": "entry",
                "journal_id": journal_id,
                "date": line["date"],
                "company_id": _id(loan.get("company_id")),
                "origin": loan["name"],
                "note": "Loan payment",
                "line_ids": [
                    {
                        "account_id": loan_account,
                        "name": "Principal",
                        "debit": _number(line["principal"]),
                        "credit": Decimal(0),
                    },
                    {
                        "account_id": interest_account,
                        "name": "Interest",
                        "debit": _number(line["interest"]),
                        "credit": Decimal(0),
                    },
                    {
                        "account_id": bank_account,
                        "name": "Loan payment",
                        "debit": Decimal(0),
                        "credit": _number(line["principal"]) + _number(line["interest"]),
                    },
                ],
            }
        )
        posting.post(env, entry_id)
        env["accounting.loan_line"].write(
            [line["id"]], {"state": "posted", "move_id": entry_id}
        )
        posted += 1
    return {"ok": True, "message": f"{posted} loan payments posted."}


# -- deferrals ------------------------------------------------------------
def compute_deferral(env: Env, deferral_id: int) -> dict[str, Any]:
    rows = env["accounting.deferral"].read([deferral_id])
    if not rows:
        raise ValidationError("deferral not found")
    deferral = rows[0]
    periods = int(deferral.get("periods") or 12)
    amount = _number(deferral.get("amount"))
    if periods <= 0 or amount <= 0:
        raise ValidationError("a deferral needs an amount and a positive period count")
    line_model = env["accounting.deferral_line"]
    line_model.unlink([row["id"] for row in deferral.get("line_ids", [])])
    monthly = (amount / periods).quantize(Decimal("0.01"))
    remaining = amount
    from ..models.closing import month_add

    for index in range(periods):
        share = monthly if index < periods - 1 else remaining
        remaining -= share
        line_model.create(
            {
                "deferral_id": deferral_id,
                "date": month_add(deferral["date_start"], index),
                "amount": share,
            }
        )
    env["accounting.deferral"].write([deferral_id], {"state": "running"})
    return {"ok": True, "message": f"Deferral spread over {periods} periods.", "state": "running"}


def post_deferral(env: Env, deferral_id: int) -> dict[str, Any]:
    rows = env["accounting.deferral"].read([deferral_id])
    if not rows:
        raise ValidationError("deferral not found")
    deferral = rows[0]
    account_id = _id(deferral.get("account_id"))
    counterpart_id = _id(deferral.get("counterpart_account_id"))
    journal_id = _id(deferral.get("journal_id"))
    if not all((account_id, counterpart_id, journal_id)):
        raise ValidationError("the deferral is missing accounts or a journal")
    posted = 0
    for line in env["accounting.deferral_line"].read(
        [row["id"] for row in deferral.get("line_ids", [])]
    ):
        if line["state"] == "posted" or line["date"] > dt.date.today():
            continue
        amount = _number(line["amount"])
        if deferral["kind"] == "revenue":
            debit, credit = counterpart_id, account_id
        else:
            debit, credit = account_id, counterpart_id
        entry_id = env["accounting.move"].create(
            {
                "move_type": "entry",
                "journal_id": journal_id,
                "date": line["date"],
                "company_id": _id(deferral.get("company_id")),
                "origin": deferral["name"],
                "note": "Deferral recognition",
                "line_ids": [
                    {
                        "account_id": debit,
                        "name": "Recognition",
                        "debit": amount,
                        "credit": Decimal(0),
                    },
                    {
                        "account_id": credit,
                        "name": "Recognition",
                        "debit": Decimal(0),
                        "credit": amount,
                    },
                ],
            }
        )
        posting.post(env, entry_id)
        env["accounting.deferral_line"].write(
            [line["id"]], {"state": "posted", "move_id": entry_id}
        )
        posted += 1
    return {"ok": True, "message": f"{posted} recognition entries posted."}


# -- follow-ups -----------------------------------------------------------
def send_followup(env: Env, move_id: int) -> dict[str, Any]:
    rows = env["accounting.move"].read([move_id])
    if not rows:
        raise ValidationError("invoice not found")
    invoice = rows[0]
    if invoice["move_type"] != "out_invoice" or invoice["state"] != "posted":
        raise ValidationError("only a posted customer invoice can be followed up")
    residual = _number(invoice.get("amount_residual"))
    if residual <= EPS:
        raise ValidationError("this invoice has nothing outstanding")
    partner = _read_one(env, "core.partner", invoice.get("partner_id"))
    levels = env["accounting.followup_level"].read(
        env["accounting.followup_level"].search([("active", "=", True)], order="delay_days")
    )
    due = invoice.get("due_date") or invoice["date"]
    overdue = (dt.date.today() - due).days
    level = levels[0] if levels else {"name": "Reminder", "delay_days": 0}
    for candidate in levels:
        if overdue >= int(candidate.get("delay_days") or 0):
            level = candidate
    body = (
        f"Follow-up level {level['name']} for {invoice['name']}: "
        f"{residual:,.2f} outstanding since {due}."
    )
    existing = env["chatter.message"].search(
        [
            ("model", "=", "accounting.move"),
            ("res_id", "=", move_id),
            ("body", "=", body),
        ],
        limit=1,
    )
    from ....config import Settings
    from ....services.mail import send_report

    path = send_report(
        Settings.from_env().mail_dir,
        recipient=partner.get("email") or "unspecified@example.test",
        subject=f"Reminder {invoice['name']}",
        body=body,
        attachment_name=f"followup-{invoice['name']}.html",
        attachment_html=f"<h1>{invoice['name']}</h1><p>{body}</p>",
        metadata={"move_id": move_id, "level": level["name"]},
    )
    if not existing:
        env["chatter.message"].create(
            {
                "model": "accounting.move",
                "res_id": move_id,
                "body": body,
                "author_id": env.uid,
                "message_type": "note",
            }
        )
    return {
        "ok": True,
        "message": f"Follow-up sent to {partner.get('name') or 'the customer'}.",
        "file": path.name,
    }


def send_due_followups(env: Env) -> int:
    ids = env["accounting.move"].search(
        [("move_type", "=", "out_invoice"), ("state", "=", "posted"), ("amount_residual", ">", 0)]
    )
    sent = 0
    for invoice in env["accounting.move"].read(ids):
        due = invoice.get("due_date") or invoice["date"]
        if due >= dt.date.today():
            continue
        try:
            send_followup(env, invoice["id"])
            sent += 1
        except ValidationError:
            continue
    return sent


# -- e-invoicing ----------------------------------------------------------
def generate_etims(env: Env, move_id: int) -> dict[str, Any]:
    """Build a KRA eTIMS payload for a posted customer invoice, once."""
    rows = env["accounting.move"].read([move_id])
    if not rows:
        raise ValidationError("invoice not found")
    invoice = rows[0]
    if invoice["state"] != "posted":
        raise ValidationError("eTIMS payloads are generated only for posted invoices")
    if invoice["move_type"] not in ("out_invoice", "out_refund"):
        raise ValidationError("eTIMS payloads apply to customer invoices")
    existing = env["accounting.edi_document"].search([("move_id", "=", move_id)], limit=1)
    if existing:
        doc = env["accounting.edi_document"].read([existing[0]])[0]
        return {
            "ok": True,
            "message": "A payload already exists for this invoice.",
            "document_id": existing[0],
            "payload": doc.get("payload") or "",
        }
    partner = _read_one(env, "core.partner", invoice.get("partner_id"))
    lines = []
    for line in invoice.get("line_ids", []):
        if line["kind"] not in ("product", "tax"):
            continue
        lines.append(
            {
                "label": line.get("name"),
                "quantity": float(line.get("qty") or 0),
                "amount": str(_number(line.get("subtotal") or line.get("debit") or line.get("credit"))),
            }
        )
    payload = json.dumps(
        {
            "invoice": invoice["name"],
            "date": str(invoice["date"]),
            "partner": {"name": partner.get("name"), "pin": partner.get("vat")},
            "currency": (invoice.get("currency_id") or {}).get("name"),
            "total": str(_number(invoice.get("amount_total"))),
            "tax": str(_number(invoice.get("amount_tax"))),
            "lines": lines,
        },
        indent=2,
    )
    doc_id = env["accounting.edi_document"].create(
        {
            "name": f"ETIMS/{invoice['name']}",
            "move_id": move_id,
            "status": "draft",
            "payload": payload,
            "generated_at": dt.datetime.now(dt.UTC),
        }
    )
    env["chatter.message"].create(
        {
            "model": "accounting.move",
            "res_id": move_id,
            "body": f"eTIMS payload generated as {invoice['name']}.",
            "author_id": env.uid,
            "message_type": "note",
        }
    )
    return {"ok": True, "message": "eTIMS payload generated.", "document_id": doc_id, "payload": payload}


# -- bank statements and write-off ---------------------------------------
def import_statement(env: Env, statement_id: int, payload: str | None = None) -> dict[str, Any]:
    rows = env["accounting.bank_statement"].read([statement_id])
    if not rows:
        raise ValidationError("statement not found")
    statement = rows[0]
    text = payload if payload is not None else (statement.get("import_payload") or "")
    if not text.strip():
        raise ValidationError("paste CSV rows as date,label,amount")
    created = 0
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.lower().startswith("date,"):
            continue
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) < 3:
            raise ValidationError(f"cannot read statement row {raw!r}")
        try:
            date = dt.date.fromisoformat(parts[0])
            amount = Decimal(parts[-1])
        except ValueError:
            raise ValidationError(f"cannot read statement row {raw!r}") from None
        env["accounting.bank_statement_line"].create(
            {
                "statement_id": statement_id,
                "date": date,
                "label": ",".join(parts[1:-1]) or "Statement line",
                "amount": amount,
            }
        )
        created += 1
    env["accounting.bank_statement"].write([statement_id], {"state": "imported"})
    return {"ok": True, "message": f"{created} statement lines imported.", "created": created}


def match_statement(env: Env, statement_id: int) -> dict[str, Any]:
    rows = env["accounting.bank_statement"].read([statement_id])
    if not rows:
        raise ValidationError("statement not found")
    lines = env["accounting.bank_statement_line"].search(
        [("statement_id", "=", statement_id), ("state", "=", "pending")]
    )
    matched = 0
    for line in env["accounting.bank_statement_line"].read(lines):
        amount = _number(line["amount"])
        candidates = env["accounting.payment"].search(
            [("state", "=", "posted")], order="-id"
        )
        for payment in env["accounting.payment"].read(candidates):
            if abs(_number(payment["amount_company"]) - abs(amount)) <= EPS:
                env["accounting.bank_statement_line"].write(
                    [line["id"]],
                    {
                        "state": "matched",
                        "payment_id": payment["id"],
                        "partner_id": _id(payment.get("partner_id")),
                    },
                )
                matched += 1
                break
    return {"ok": True, "message": f"{matched} statement lines matched.", "matched": matched}


def write_off_invoice(
    env: Env,
    invoice_id: int,
    *,
    received_amount: Decimal | float | None = None,
    account_id: int | None = None,
    date: dt.date | None = None,
) -> dict[str, Any]:
    """Settle an invoice with a partial receipt and a balanced write-off."""
    rows = env["accounting.move"].read([invoice_id])
    if not rows:
        raise ValidationError("invoice not found")
    invoice = rows[0]
    if invoice["state"] != "posted" or invoice["move_type"] != "out_invoice":
        raise ValidationError("only a posted customer invoice can be written off")
    payments.recompute_invoice(env, [invoice_id])
    current = _number(env["accounting.move"].read([invoice_id])[0]["amount_residual"])
    received = _number(received_amount if received_amount is not None else 0)
    if received < 0 or received >= current:
        raise ValidationError("the received amount must be between zero and the residual")
    settings = _settings(env, _id(invoice.get("company_id")))
    writeoff_account = account_id or _id(settings.get("expense_account_id"))
    bank_account = _id(settings.get("bank_account_id"))
    receivable = _id(settings.get("receivable_account_id"))
    journal_ids = env["accounting.journal"].search([("code", "=", "BNK")], limit=1)
    if not all((writeoff_account, bank_account, receivable, journal_ids)):
        raise ValidationError("bank, receivable or write-off accounts are not configured")
    difference = current - received
    entry_id = env["accounting.move"].create(
        {
            "move_type": "entry",
            "journal_id": journal_ids[0],
            "partner_id": _id(invoice.get("partner_id")),
            "date": date or dt.date.today(),
            "company_id": _id(invoice.get("company_id")),
            "origin": invoice["name"],
            "note": "Reconciliation write-off",
            "line_ids": [
                {
                    "account_id": bank_account,
                    "name": "Received",
                    "debit": received,
                    "credit": Decimal(0),
                },
                {
                    "account_id": writeoff_account,
                    "name": "Write-off",
                    "debit": difference,
                    "credit": Decimal(0),
                },
                {
                    "account_id": receivable,
                    "name": "Settled",
                    "debit": Decimal(0),
                    "credit": current,
                },
            ],
        }
    )
    posting.post(env, entry_id)
    any_model: Any = env["accounting.payment"]
    payment_id = any_model.create(
        {
            "name": f"WO/{invoice['name']}",
            "payment_type": "inbound",
            "partner_id": _id(invoice.get("partner_id")),
            "journal_id": journal_ids[0],
            "amount": current,
            "amount_company": current,
            "date": date or dt.date.today(),
            "method": "writeoff",
            "memo": "Write-off",
            "state": "posted",
            "company_id": _id(invoice.get("company_id")),
            "payment_line_ids": [{"move_id": invoice_id, "amount": current}],
        }
    )
    payments.recompute_invoice(env, [invoice_id])
    return {
        "ok": True,
        "message": f"Invoice settled with a {difference:,.2f} write-off.",
        "payment_id": payment_id,
        "writeoff_move_id": entry_id,
    }


def reconcile_models_hint(env: Env, line: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first reconciliation model matching a statement line."""
    for model in env["accounting.reconciliation_model"].read(
        env["accounting.reconciliation_model"].search([("active", "=", True)], order="sequence")
    ):
        if model["rule_type"] == "amount" and abs(
            _number(model.get("pattern")) - abs(_number(line["amount"]))
        ) <= EPS:
            return model
        if (
            model["rule_type"] == "label"
            and model.get("pattern")
            and str(model["pattern"]).lower() in str(line.get("label") or "").lower()
        ):
            return model
    return None
