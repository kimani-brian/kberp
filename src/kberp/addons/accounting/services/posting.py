"""Posting, cancellation, reversal and account balances."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from ....services.events import emit
from .api import compute_taxes

INVOICE_TYPES = {"out_invoice", "in_invoice", "out_refund", "in_refund"}


def _amount(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def _audit(env: Env, move_id: int, action: str, detail: str) -> None:
    env["accounting.audit_log"].create(
        {
            "move_id": move_id,
            "action": action,
            "user_id": env.uid,
            "detail": detail,
        }
    )


def _settings(env: Env, move: dict[str, Any]) -> dict[str, Any]:
    company = move.get("company_id") or {}
    company_id = company.get("id") if isinstance(company, dict) else company
    domain = [("company_id", "=", int(company_id))] if company_id else []
    ids = env["accounting.settings"].search(domain, limit=1)
    if not ids:
        ids = env["accounting.settings"].search([], limit=1)
    if not ids:
        raise ValidationError("accounting settings are missing")
    return env["accounting.settings"].read([ids[0]])[0]


def recompute_move(env: Env, move_ids: list[int]) -> None:
    """Rebuild tax and balancing lines for invoices, then refresh totals."""
    if not move_ids:
        return
    safe_env = env.with_context(allow_posting=True)
    move_model = safe_env["accounting.move"]
    line_model = safe_env["accounting.move_line"]
    for move in move_model.read(move_ids):
        if move["state"] == "posted" or move["move_type"] == "entry":
            continue
        lines = line_model.read([line["id"] for line in move.get("line_ids", [])])
        products = [line for line in lines if line["kind"] == "product"]
        generated = [line["id"] for line in lines if line["kind"] in ("tax", "receivable", "payable")]
        if generated:
            line_model.unlink(generated)

        customer = move["move_type"] in ("out_invoice", "out_refund")
        untaxed = Decimal(0)
        for line in products:
            subtotal = _amount(line["price_unit"]) * _amount(line["qty"] or 1)
            untaxed += subtotal
            line_model.write(
                [line["id"]],
                {
                    "subtotal": subtotal,
                    "debit": Decimal(0) if customer else subtotal,
                    "credit": subtotal if customer else Decimal(0),
                },
            )

        tax_total = Decimal(0)
        for line in products:
            tax_ids = [tax["id"] for tax in line.get("tax_ids") or []]
            if not tax_ids:
                continue
            entries, amount = compute_taxes(
                env, tax_ids, line.get("subtotal") or _amount(line["price_unit"]) * _amount(line["qty"] or 1)
            )
            tax_total += amount
            settings = _settings(env, move)
            default_tax_account = (settings.get("tax_account_id") or {}).get("id")
            for entry in entries:
                account_id = entry.get("account_id") or default_tax_account
                if not account_id:
                    raise ValidationError(f"tax {entry['name']} has no account")
                line_model.create(
                    {
                        "move_id": move["id"],
                        "account_id": account_id,
                        "name": entry["name"],
                        "debit": Decimal(0) if customer else entry["amount"],
                        "credit": entry["amount"] if customer else Decimal(0),
                        "kind": "tax",
                        "tax_id": entry.get("tax_id"),
                        "date": move["date"],
                    }
                )

        total = untaxed + tax_total
        settings = _settings(env, move)
        kind = "receivable" if customer else "payable"
        account_field = "receivable_account_id" if customer else "payable_account_id"
        account = settings.get(account_field) or {}
        account_id = account.get("id") if isinstance(account, dict) else account
        if not account_id:
            raise ValidationError(f"{kind} account is not configured")
        line_model.create(
            {
                "move_id": move["id"],
                "account_id": account_id,
                "partner_id": (move.get("partner_id") or {}).get("id"),
                "name": "Amount due" if customer else "Amount payable",
                "debit": total if customer else Decimal(0),
                "credit": Decimal(0) if customer else total,
                "kind": kind,
                "date": move["date"],
            }
        )
        env.with_context(skip_totals=True)["accounting.move"].write(
            [move["id"]],
            {"amount_untaxed": untaxed, "amount_tax": tax_total, "amount_total": total},
        )


def post(env: Env, move_id: int) -> dict[str, Any]:
    """Post a draft move, allocate its number and write the audit trail."""
    rows = env["accounting.move"].read([move_id])
    if not rows:
        raise ValidationError("entry not found")
    move = rows[0]
    if move["state"] != "draft":
        raise ValidationError(f"cannot post a {move['state']} entry")
    from .closing import check_locked

    check_locked(env, move)
    if not move["move_type"]:
        raise ValidationError("entry type is missing")
    safe_env = env.with_context(allow_posting=True)
    lines = safe_env["accounting.move_line"].read(
        [line["id"] for line in move.get("line_ids", [])]
    )
    if not lines:
        raise ValidationError("add at least two lines before posting")
    debit = sum((_amount(line["debit"]) for line in lines), Decimal(0))
    credit = sum((_amount(line["credit"]) for line in lines), Decimal(0))
    if debit != credit:
        raise ValidationError(
            f"entry is not balanced: debit {debit:,.2f} vs credit {credit:,.2f}"
        )
    journal = safe_env["accounting.journal"].read([move["journal_id"]["id"]])[0]
    sequence = journal.get("sequence_id") or {}
    sequence_id = sequence.get("id") if isinstance(sequence, dict) else sequence
    if not sequence_id:
        raise ValidationError(f"journal {journal['name']} has no number sequence")
    sequence_model: Any = safe_env["core.ir_sequence"]
    sequence_row = sequence_model.read([int(sequence_id)])[0]
    number = sequence_model.next_code(sequence_row["xml_id"])
    safe_env["accounting.move"].write(
        [move_id],
        {"state": "posted", "name": number, "amount_debit": debit, "amount_credit": credit},
    )
    _audit(env, move_id, "post", f"Posted as {number}")
    emit(
        env,
        "accounting.move.posted",
        {
            "move_id": move_id,
            "partner_id": (move.get("partner_id") or {}).get("id"),
            "company_id": (move.get("company_id") or {}).get("id"),
            "number": number,
            "origin": move.get("origin") or "",
            "move_type": move["move_type"],
        },
    )
    return {"ok": True, "message": f"Entry posted as {number}.", "state": "posted", "name": number}


def cancel(env: Env, move_id: int) -> dict[str, Any]:
    """Cancel a draft or posted entry, keeping its number."""
    rows = env["accounting.move"].read([move_id])
    if not rows:
        raise ValidationError("entry not found")
    move = rows[0]
    if move["state"] not in ("draft", "posted"):
        raise ValidationError(f"cannot cancel a {move['state']} entry")
    env.with_context(allow_posting=True)["accounting.move"].write(
        [move_id], {"state": "cancel"}
    )
    _audit(env, move_id, "cancel", "Cancelled")
    return {"ok": True, "message": "Entry cancelled.", "state": "cancel"}


def reverse(env: Env, move_id: int) -> dict[str, Any]:
    """Create and post a compensating entry, the only correction after posting."""
    rows = env["accounting.move"].read([move_id])
    if not rows:
        raise ValidationError("entry not found")
    original = rows[0]
    if original["state"] != "posted":
        raise ValidationError("only a posted entry can be reversed")
    safe_env = env.with_context(allow_posting=True)
    lines = safe_env["accounting.move_line"].read(
        [line["id"] for line in original.get("line_ids", [])]
    )
    reversal_id = safe_env["accounting.move"].create(
        {
            "move_type": original["move_type"],
            "partner_id": (original.get("partner_id") or {}).get("id"),
            "journal_id": original["journal_id"]["id"],
            "date": dt.date.today(),
            "company_id": (original.get("company_id") or {}).get("id"),
            "currency_id": (original.get("currency_id") or {}).get("id"),
            "origin": original["name"],
            "note": f"Reversal of {original['name']}",
            "state": "draft",
        }
    )
    for line in lines:
        safe_env["accounting.move_line"].create(
            {
                "move_id": reversal_id,
                "account_id": line["account_id"]["id"],
                "partner_id": (line.get("partner_id") or {}).get("id"),
                "name": line.get("name") or "Reversal",
                "debit": _amount(line["credit"]),
                "credit": _amount(line["debit"]),
                "kind": line["kind"],
                "date": dt.date.today(),
            }
        )
    result = post(safe_env, reversal_id)
    _audit(env, move_id, "reverse", f"Reversed by {result['name']}")
    return {
        "ok": True,
        "message": f"Reversed as {result['name']}.",
        "state": "posted",
        "reversal_id": reversal_id,
    }


def balances(env: Env) -> dict[str, Decimal]:
    """Totals by account type from posted lines only."""
    result: dict[str, Decimal] = {}
    move_ids = env["accounting.move"].search([("state", "=", "posted")])
    if not move_ids:
        return result
    moves = {row["id"]: row for row in env["accounting.move"].read(move_ids)}
    line_ids: list[int] = []
    for move in moves.values():
        line_ids.extend(line["id"] for line in move.get("line_ids", []))
    if not line_ids:
        return result
    for line in env["accounting.move_line"].read(line_ids):
        account = line.get("account_id") or {}
        account_id = account.get("id") if isinstance(account, dict) else account
        if not account_id:
            continue
        row = env["accounting.account"].read([int(account_id)])[0]
        delta = _amount(line["debit"]) - _amount(line["credit"])
        result[row["type"]] = result.get(row["type"], Decimal(0)) + delta
    return result
