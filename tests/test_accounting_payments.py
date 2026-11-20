"""A2: payments, reconciliation, credit notes and currency differences."""

from __future__ import annotations

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.accounting.services.api import create_invoice
from kberp.addons.accounting.services.payments import (
    cancel_payment,
    create_credit_note,
    recompute_invoice,
    register_payment,
)
from kberp.env import Env
from kberp.orm.model import ValidationError
from kberp.services.actions import invoke
from kberp.web.app import Application

PAYMENTS = "accounting.action_payment_inbound"


@pytest.fixture()
def admin(client):
    return login(client)


def _product(env: Env) -> int:
    return env["core.product_template"].search([], limit=1)[0]


def _journal(env: Env, code: str = "BNK") -> int:
    return env["accounting.journal"].search([("code", "=", code)], limit=1)[0]


def _posted_invoice(env: Env, total: int = 1000, origin: str | None = None, currency=None):
    import uuid

    invoice_id = create_invoice(
        env,
        partner_id=1,
        company_id=1,
        origin=origin or f"A2/{uuid.uuid4().hex[:8]}",
        currency_id=currency,
        lines=[{"product_id": _product(env), "name": "Pallet", "qty": 1, "price_unit": total}],
    )
    invoke(env, "accounting.move", "action_post", invoice_id)
    return invoice_id


def test_payment_terms_and_exchange_account_are_seeded(env):
    assert env["accounting.payment_term"].search([])
    settings = env["accounting.settings"].read(env["accounting.settings"].search([], limit=1))[0]
    assert settings["exchange_account_id"]
    assert env["accounting.fiscal_position"].search([])


def test_partial_then_full_payment(app: Application, env):
    invoice_id = _posted_invoice(env)
    with app.db.transaction():
        register_payment(env, invoice_id, amount=400, journal_id=_journal(env))
    recompute_invoice(env, [invoice_id])
    row = env["accounting.move"].read([invoice_id])[0]
    assert row["payment_state"] == "partial"
    assert row["amount_residual"] == 600

    with app.db.transaction():
        register_payment(env, invoice_id, amount=600, journal_id=_journal(env))
    recompute_invoice(env, [invoice_id])
    row = env["accounting.move"].read([invoice_id])[0]
    assert row["payment_state"] == "paid"
    assert row["amount_residual"] == 0

    with pytest.raises(ValidationError, match="exceeds the outstanding"), app.db.transaction():
        register_payment(env, invoice_id, amount=1, journal_id=_journal(env))


def test_one_payment_allocated_across_two_invoices(app: Application, env):
    first = _posted_invoice(env, 600)
    second = _posted_invoice(env, 400)
    with app.db.transaction():
        result = register_payment(
            env,
            journal_id=_journal(env),
            allocations=[(first, 600), (second, 400)],
        )
    payment = env["accounting.payment"].read([result["payment_id"]])[0]
    assert len(payment["payment_line_ids"]) == 2
    assert payment["amount"] == 1000
    recompute_invoice(env, [first, second])
    assert [env["accounting.move"].read([row])[0]["payment_state"] for row in (first, second)] == [
        "paid",
        "paid",
    ]


def test_credit_note_reconciles_against_its_invoice(app: Application, env):
    invoice_id = _posted_invoice(env, 1000)
    with app.db.transaction():
        result = create_credit_note(env, invoice_id)
        invoke(env, "accounting.move", "action_post", result["credit_note_id"])
    recompute_invoice(env, [invoice_id])
    row = env["accounting.move"].read([invoice_id])[0]
    assert row["payment_state"] == "reversed"
    assert row["amount_residual"] <= 0
    credit = env["accounting.move"].read([result["credit_note_id"]])[0]
    assert credit["move_type"] == "out_refund"
    assert credit["amount_debit"] == credit["amount_credit"]


def test_foreign_currency_payment_posts_an_exchange_difference(app: Application, env):
    usd = env["core.currency"].search([("code", "=", "USD")], limit=1)[0]
    env["core.currency"].write([usd], {"rate": 0.0077})
    try:
        invoice_id = _posted_invoice(env, 1000, currency=usd)
        env["core.currency"].write([usd], {"rate": 0.0080})
        with app.db.transaction():
            result = register_payment(env, invoice_id, amount=1000, journal_id=_journal(env))
        payment = env["accounting.payment"].read([result["payment_id"]])[0]
        assert payment["currency_rate"] == 125
        move = env["accounting.move"].read(
            env["accounting.move"].search([("origin", "=", payment["name"])])
        )[0]
        assert move["amount_debit"] == move["amount_credit"]
        assert any(line["name"] == "Exchange difference" for line in move["line_ids"])
    finally:
        env["core.currency"].write([usd], {"rate": 0.0077})


def test_cancelled_payment_releases_the_allocation(app: Application, env):
    invoice_id = _posted_invoice(env)
    with app.db.transaction():
        result = register_payment(env, invoice_id, amount=500, journal_id=_journal(env))
    recompute_invoice(env, [invoice_id])
    assert env["accounting.move"].read([invoice_id])[0]["amount_residual"] == 500
    cancel_payment(env, result["payment_id"])
    recompute_invoice(env, [invoice_id])
    row = env["accounting.move"].read([invoice_id])[0]
    assert row["amount_residual"] == 1000
    assert row["payment_state"] == "not paid"


def test_payment_screens_and_buttons_are_available(admin: Client, env):
    aid = action_id(env, PAYMENTS)
    listing = admin.get(f"/apps/accounting/action/{aid}").get_data(as_text=True)
    assert "Customer Payments" in listing
    invoice_id = _posted_invoice(env)
    form = admin.get(f"/apps/accounting/action/{action_id(env, 'accounting.action_invoice')}/{invoice_id}").get_data(as_text=True)
    assert "Register Payment" in form
    assert "Credit Note" in form
    page = admin.get("/apps/accounting").get_data(as_text=True)
    assert "Payment Terms" in page
    assert "Fiscal Positions" in page


def test_fiscal_position_remaps_taxes_and_accounts(env):
    partner = env["core.partner"].read([1])[0]
    country = partner.get("country_id")
    if not country:
        pytest.skip("the demo customer has no country")
    vat = env["accounting.tax"].search([("amount", "=", 16)], limit=1)[0]
    zero = env["accounting.tax"].search([("name", "=", "Zero rated")], limit=1)[0]
    income = env["accounting.account"].search([("code", "=", "4000")], limit=1)[0]
    expense = env["accounting.account"].search([("code", "=", "5000")], limit=1)[0]
    position = env["accounting.fiscal_position"].create(
        {
            "name": "Test mapping",
            "country_id": country["id"],
            "source_tax_id": vat,
            "dest_tax_id": zero,
            "source_account_id": income,
            "dest_account_id": expense,
        }
    )
    try:
        invoice_id = create_invoice(
            env,
            partner_id=1,
            company_id=1,
            origin="A2/FISCAL/TEST",
            lines=[
                {
                    "product_id": _product(env),
                    "name": "Pallet",
                    "qty": 1,
                    "price_unit": 100,
                    "tax_ids": [vat],
                    "account_id": income,
                }
            ],
        )
        line = next(
            row
            for row in env["accounting.move"].read([invoice_id])[0]["line_ids"]
            if row["kind"] == "product"
        )
        assert [tax["id"] for tax in line["tax_ids"]] == [zero]
        assert line["account_id"]["id"] == expense
    finally:
        env["accounting.fiscal_position"].unlink([position])
