"""A3: lock dates, secure entries, statements, tax, eTIMS and write-offs."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from kberp.addons.accounting.services import closing, reporting
from kberp.addons.accounting.services.api import create_invoice
from kberp.addons.accounting.services.payments import register_payment
from kberp.env import Env
from kberp.orm.model import ValidationError
from kberp.services.actions import invoke
from kberp.web.app import Application


def _account(env: Env, code: str) -> int:
    return env["accounting.account"].search([("code", "=", code)], limit=1)[0]


def _journal(env: Env, code: str = "BNK") -> int:
    return env["accounting.journal"].search([("code", "=", code)], limit=1)[0]


def _product(env: Env) -> int:
    return env["core.product_template"].search([], limit=1)[0]


def _entry(env: Env, date: dt.date | None = None) -> int:
    return env["accounting.move"].create(
        {
            "move_type": "entry",
            "journal_id": env["accounting.journal"].search([("code", "=", "GEN")], limit=1)[0],
            "date": date or dt.date.today(),
            "company_id": 1,
            "line_ids": [
                {
                    "account_id": _account(env, "1010"),
                    "name": "Cash",
                    "debit": 100,
                    "credit": 0,
                },
                {
                    "account_id": _account(env, "4000"),
                    "name": "Income",
                    "debit": 0,
                    "credit": 100,
                },
            ],
        }
    )


def _posted_invoice(
    env: Env, total: float = 1000, date: dt.date | None = None
) -> int:
    invoice_id = create_invoice(
        env,
        partner_id=1,
        company_id=1,
        origin=f"A3/{uuid.uuid4().hex[:8]}",
        lines=[
            {"product_id": _product(env), "name": "Pallet", "qty": 1, "price_unit": total}
        ],
    )
    if date:
        env["accounting.move"].write([invoice_id], {"date": date})
    invoke(env, "accounting.move", "action_post", invoice_id)
    return invoice_id


def _fixture_report(env: Env, report_type: str) -> dict:
    ids = env["accounting.report"].search([("report_type", "=", report_type)], limit=1)
    assert ids, f"report {report_type} is not seeded"
    return env["accounting.report"].read([ids[0]])[0]


def _row_amount(report: dict, label: str) -> Decimal:
    for line in report.get("line_ids", []):
        if line["label"] == label:
            return Decimal(str(line["amount"]))
    raise AssertionError(f"row {label!r} not found")


def test_lock_date_rejects_backdated_postings_and_edits(app: Application, env):
    lock = env["accounting.lock_date"].search([], limit=1)[0]
    original = env["accounting.lock_date"].read([lock])[0]["date_hard"]
    move_id = _entry(env)
    try:
        env["accounting.lock_date"].write(
            [lock], {"date_hard": dt.date.today(), "reason": "Month-end close"}
        )
        with pytest.raises(ValidationError, match="lock date"):
            invoke(env, "accounting.move", "action_post", move_id)
        with pytest.raises(ValidationError, match="lock date"):
            env["accounting.move"].write([move_id], {"note": "backdated"})
    finally:
        env["accounting.lock_date"].write(
            [lock], {"date_hard": original, "reason": "Prior financial year closed"}
        )
    invoke(env, "accounting.move", "action_post", move_id)


def test_secured_entry_is_immutable(app: Application, env):
    move_id = _entry(env)
    invoke(env, "accounting.move", "action_post", move_id)
    result = closing.secure(env, move_id)
    assert result["secured"] is True
    with pytest.raises(ValidationError, match="cannot be edited"):
        env["accounting.move"].write([move_id], {"note": "changed"})
    with pytest.raises(ValidationError, match="cannot be deleted"):
        env["accounting.move"].unlink([move_id])
    with pytest.raises(ValidationError, match="lines of posted entries"):
        line_id = env["accounting.move"].read([move_id])[0]["line_ids"][0]["id"]
        env["accounting.move_line"].write([line_id], {"name": "changed"})


def test_balance_sheet_balances_and_reconciles_with_profit(app: Application, env):
    report_id = _fixture_report(env, "balance_sheet")["id"]
    reporting.run(env, report_id)
    report = env["accounting.report"].read([report_id])[0]
    assets = _row_amount(report, "Total assets")
    liabilities = _row_amount(report, "Total liabilities")
    equity = _row_amount(report, "Total equity")
    assert assets == liabilities + equity
    assert assets == _row_amount(report, "Total liabilities and equity")

    profit_id = _fixture_report(env, "profit_and_loss")["id"]
    reporting.run(env, profit_id)
    profit = env["accounting.report"].read([profit_id])[0]
    assert _row_amount(profit, "Net profit") == _row_amount(
        report, "Current profit"
    )


def test_trial_balance_and_aged_receivable_reconcile(app: Application, env):
    trial_id = _fixture_report(env, "trial_balance")["id"]
    reporting.run(env, trial_id)
    trial = env["accounting.report"].read([trial_id])[0]
    assert _row_amount(trial, "Total") == 0

    aged_id = _fixture_report(env, "aged_receivable")["id"]
    reporting.run(env, aged_id)
    aged = env["accounting.report"].read([aged_id])[0]
    expected = sum(
        Decimal(str(row["amount_residual"]))
        for row in env["accounting.move"].read(
            env["accounting.move"].search(
                [("move_type", "=", "out_invoice"), ("state", "=", "posted")]
            )
        )
    )
    assert _row_amount(aged, "Total") == expected


def test_tax_report_and_return_match_posted_tax_lines(app: Application, env):
    future = dt.date(2099, 6, 15)
    invoice_id = _posted_invoice(env, total=1000, date=future)
    invoice = env["accounting.move"].read([invoice_id])[0]
    report_id = env["accounting.report"].create(
        {
            "name": "A3 tax check",
            "report_type": "tax_report",
            "date_from": future,
            "date_to": future,
            "company_id": 1,
        }
    )
    reporting.run(env, report_id)
    report = env["accounting.report"].read([report_id])[0]
    assert _row_amount(report, "Total tax due") == Decimal(
        str(invoice["amount_tax"])
    )
    env["accounting.report"].unlink([report_id])

    return_id = env["accounting.tax_return"].create(
        {
            "name": "A3 interim return",
            "date_from": future,
            "date_to": future,
            "company_id": 1,
        }
    )
    closing.compute_tax_return(env, return_id)
    tax_return = env["accounting.tax_return"].read([return_id])[0]
    assert tax_return["amount_total"] == invoice["amount_tax"]
    env["accounting.tax_return"].unlink([return_id])


def test_etims_payload_only_for_posted_invoices(app: Application, env):
    draft_id = create_invoice(
        env,
        partner_id=1,
        company_id=1,
        origin=f"A3-draft/{uuid.uuid4().hex[:8]}",
        lines=[
            {"product_id": _product(env), "name": "Pallet", "qty": 1, "price_unit": 50}
        ],
    )
    with pytest.raises(ValidationError, match="posted invoices"):
        closing.generate_etims(env, draft_id)
    invoke(env, "accounting.move", "action_post", draft_id)
    first = closing.generate_etims(env, draft_id)
    second = closing.generate_etims(env, draft_id)
    assert first["document_id"] == second["document_id"]
    assert draft_id in [
        row["move_id"]["id"]
        for row in env["accounting.edi_document"].read(
            env["accounting.edi_document"].search([])
        )
    ]
    assert env["accounting.audit_log"].search([("move_id", "=", draft_id)])


def test_write_off_settles_the_invoice_with_a_balanced_entry(app: Application, env):
    invoice_id = _posted_invoice(env, total=100)
    with app.db.transaction():
        result = closing.write_off_invoice(env, invoice_id, received_amount=40)
    invoice = env["accounting.move"].read([invoice_id])[0]
    assert invoice["amount_residual"] == 0
    entry = env["accounting.move"].read([result["writeoff_move_id"]])[0]
    assert entry["state"] == "posted"
    assert entry["amount_debit"] == entry["amount_credit"] == 100
    assert result["payment_id"]


def test_statement_import_and_match(app: Application, env):
    invoice_id = _posted_invoice(env, total=321.45)
    with app.db.transaction():
        register_payment(env, invoice_id, amount=321.45, journal_id=_journal(env))
    statement_id = env["accounting.bank_statement"].create(
        {
            "name": f"ST/{uuid.uuid4().hex[:6]}",
            "journal_id": _journal(env),
            "date": dt.date.today(),
            "company_id": 1,
        }
    )
    result = closing.import_statement(
        env, statement_id, f"{dt.date.today().isoformat()},Customer receipt,321.45"
    )
    assert result["created"] == 1
    matched = closing.match_statement(env, statement_id)
    assert matched["matched"] == 1
    lines = env["accounting.bank_statement"].read([statement_id])[0]["line_ids"]
    assert lines[0]["state"] == "matched"
    assert lines[0]["payment_id"]


def test_asset_loan_and_deferral_postings_are_balanced(app: Application, env):
    asset_id = env["accounting.asset"].search([], limit=1)[0]
    loan_id = env["accounting.loan"].search([], limit=1)[0]
    deferral_id = env["accounting.deferral"].search([], limit=1)[0]
    with app.db.transaction():
        closing.post_depreciation(env, asset_id)
        closing.post_loan(env, loan_id)
        closing.post_deferral(env, deferral_id)
    checks = [
        ("accounting.asset_line", "asset_id", asset_id),
        ("accounting.loan_line", "loan_id", loan_id),
        ("accounting.deferral_line", "deferral_id", deferral_id),
    ]
    for model, field, record_id in checks:
        rows = env[model].read(env[model].search([(field, "=", record_id)]))
        posted = [row for row in rows if row["state"] == "posted"]
        assert posted, f"no posted rows for {model}"
        for row in posted:
            move = env["accounting.move"].read([row["move_id"]["id"]])[0]
            assert move["state"] == "posted"
            assert move["amount_debit"] == move["amount_credit"]
