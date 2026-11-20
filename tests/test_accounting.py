"""A1: chart of accounts, tax engine, posting and immutability."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from conftest import action_id, csrf_from, login
from werkzeug.test import Client

from kberp.env import Env
from kberp.orm.model import ValidationError
from kberp.services.actions import invoke
from kberp.web.app import Application

ENTRY = "accounting.action_journal_entry"
INVOICE = "accounting.action_invoice"


@pytest.fixture()
def admin(client):
    return login(client)


def _account(env: Env, code: str) -> int:
    return env["accounting.account"].search([("code", "=", code)], limit=1)[0]


def _journal(env: Env, code: str) -> int:
    return env["accounting.journal"].search([("code", "=", code)], limit=1)[0]


def _move(env: Env, **overrides):
    values = {
        "move_type": "entry",
        "journal_id": _journal(env, "GEN"),
        "date": dt.date.today(),
        "company_id": 1,
        **overrides,
    }
    return env["accounting.move"].create(values)


def test_chart_journals_and_defaults_are_seeded(env):
    assert len(env["accounting.account"].search([])) >= 8
    journals = env["accounting.journal"].read(env["accounting.journal"].search([]))
    assert {row["code"] for row in journals} == {"GEN", "SAL", "PUR", "BNK", "CSH", "INV"}
    assert all(row["sequence_id"] for row in journals)
    settings = env["accounting.settings"].read(
        env["accounting.settings"].search([], limit=1)
    )[0]
    assert settings["receivable_account_id"]
    assert settings["payable_account_id"]
    assert settings["tax_account_id"]


def test_tax_engine_covers_both_price_bases_and_fixed_amounts(env):
    from kberp.addons.accounting.services.api import compute_taxes

    vat = env["accounting.tax"].search(
        [("xml_id", "=", "accounting.tax_vat_16")], limit=1
    )[0]
    lines, total = compute_taxes(env, [vat], Decimal(1000))
    assert total == Decimal("160.00")
    assert lines[0]["account_id"]

    lines, total = compute_taxes(env, [vat], Decimal(1000), price_include=True)
    assert total == Decimal("137.93")

    env["accounting.tax"].write([vat], {"amount_type": "fixed", "amount": 50})
    try:
        _, total = compute_taxes(env, [vat], Decimal(1000), quantity=2)
        assert total == Decimal("100.00")
    finally:
        env["accounting.tax"].write([vat], {"amount_type": "percent", "amount": 16})


def test_tax_engine_groups_multiple_taxes_and_rounding_modes(env):
    from kberp.addons.accounting.services.api import compute_taxes

    taxes = env["accounting.tax"].search([], limit=2)
    lines, total = compute_taxes(env, taxes, Decimal("100.05"))
    assert len(lines) >= 2
    assert total >= Decimal(0)

    vat = env["accounting.tax"].search(
        [("xml_id", "=", "accounting.tax_vat_16")], limit=1
    )[0]
    _, per_line = compute_taxes(env, [vat], Decimal("99.99"), rounding="line")
    _, per_total = compute_taxes(env, [vat], Decimal("99.99"), rounding="total")
    assert per_line == per_total == Decimal("16.00")


def test_balanced_entry_posts_and_allocates_contiguous_numbers(env):
    first = _move(
        env,
        line_ids=[
            {"account_id": _account(env, "1010"), "name": "Cash", "debit": 1000, "credit": 0},
            {"account_id": _account(env, "4000"), "name": "Income", "debit": 0, "credit": 1000},
        ],
    )
    second = _move(
        env,
        line_ids=[
            {"account_id": _account(env, "1010"), "name": "Cash", "debit": 500, "credit": 0},
            {"account_id": _account(env, "4000"), "name": "Income", "debit": 0, "credit": 500},
        ],
    )
    r1 = invoke(env, "accounting.move", "action_post", first)
    r2 = invoke(env, "accounting.move", "action_post", second)
    assert r1["name"].startswith("GEN/") and r2["name"].startswith("GEN/")
    assert int(r2["name"].rsplit("/", 1)[1]) == int(r1["name"].rsplit("/", 1)[1]) + 1
    row = env["accounting.move"].read([first])[0]
    assert row["state"] == "posted"
    assert row["amount_debit"] == row["amount_credit"] == Decimal(1000)
    assert env["accounting.audit_log"].search([("move_id", "=", first)])


def test_unbalanced_entry_is_rejected_with_amounts(env):
    move_id = _move(
        env,
        line_ids=[
            {"account_id": _account(env, "1010"), "name": "Cash", "debit": 1200, "credit": 0},
            {"account_id": _account(env, "4000"), "name": "Income", "debit": 0, "credit": 1150},
        ],
    )
    with pytest.raises(ValidationError) as excinfo:
        invoke(env, "accounting.move", "action_post", move_id)
    message = str(excinfo.value)
    assert "1,200.00" in message and "1,150.00" in message
    assert env["accounting.move"].read([move_id])[0]["state"] == "draft"


def test_posted_entry_is_immutable_even_for_the_administrator(env):
    move_id = _move(
        env,
        line_ids=[
            {"account_id": _account(env, "1010"), "name": "Cash", "debit": 100, "credit": 0},
            {"account_id": _account(env, "4000"), "name": "Income", "debit": 0, "credit": 100},
        ],
    )
    invoke(env, "accounting.move", "action_post", move_id)
    with pytest.raises(ValidationError, match="cannot be edited"):
        env["accounting.move"].write([move_id], {"note": "changed"})
    with pytest.raises(ValidationError, match="cannot be deleted"):
        env["accounting.move"].unlink([move_id])
    line_id = env["accounting.move"].read([move_id])[0]["line_ids"][0]["id"]
    with pytest.raises(ValidationError, match="lines of posted entries"):
        env["accounting.move_line"].write([line_id], {"name": "changed"})

    result = invoke(env, "accounting.move", "action_reverse", move_id)
    assert result["state"] == "posted"
    assert env["accounting.move"].read([result["reversal_id"]])[0]["origin"]
    assert env["accounting.audit_log"].search(
        [("move_id", "=", move_id), ("action", "=", "reverse")]
    )


def test_draft_entry_can_be_cancelled_and_deleted(env):
    move_id = _move(
        env,
        line_ids=[
            {"account_id": _account(env, "1010"), "name": "Cash", "debit": 100, "credit": 0},
            {"account_id": _account(env, "4000"), "name": "Income", "debit": 0, "credit": 100},
        ],
    )
    invoke(env, "accounting.move", "action_cancel", move_id)
    assert env["accounting.move"].read([move_id])[0]["state"] == "cancel"
    env["accounting.move"].unlink([move_id])
    assert not env["accounting.move"].read([move_id])


def _invoice(env):
    vat = env["accounting.tax"].search(
        [("xml_id", "=", "accounting.tax_vat_16")], limit=1
    )[0]
    product = env["core.product_template"].search([], limit=1)[0]
    return env["accounting.move"].create(
        {
            "move_type": "out_invoice",
            "journal_id": _journal(env, "SAL"),
            "date": dt.date.today(),
            "partner_id": 1,
            "company_id": 1,
            "line_ids": [
                {
                    "product_id": product,
                    "name": "Pallet",
                    "qty": 2,
                    "price_unit": 1000,
                    "tax_ids": [vat],
                }
            ],
        }
    )


def test_invoice_totals_receivable_line_and_balances(env):
    from kberp.addons.accounting.services.posting import balances

    move_id = _invoice(env)
    row = env["accounting.move"].read([move_id])[0]
    assert row["amount_untaxed"] == Decimal(2000)
    assert row["amount_tax"] == Decimal(320)
    assert row["amount_total"] == Decimal(2320)
    kinds = {line["kind"] for line in row["line_ids"]}
    assert {"product", "tax", "receivable"} <= kinds
    receivable = next(line for line in row["line_ids"] if line["kind"] == "receivable")
    assert receivable["debit"] == Decimal(2320)

    invoke(env, "accounting.move", "action_post", move_id)
    totals = balances(env)
    assert totals["receivable"] >= Decimal(2320)
    assert totals["income"] <= Decimal(-2000)
    assert totals["liability"] <= Decimal(-320)


def test_accounting_shell_shows_kpis_and_screens(admin: Client, env):
    page = admin.get("/apps/accounting").get_data(as_text=True)
    assert "Ledger at a glance" in page
    assert "Posted entries" in page
    assert "Chart of Accounts" in page
    assert "Invoices" in page

    aid = action_id(env, ENTRY)
    listing = admin.get(f"/apps/accounting/action/{aid}").get_data(as_text=True)
    assert "Journal Entries" in listing


def test_post_button_route_works_from_the_form(admin: Client, env):
    move_id = _move(
        env,
        line_ids=[
            {"account_id": _account(env, "1010"), "name": "Cash", "debit": 100, "credit": 0},
            {"account_id": _account(env, "4000"), "name": "Income", "debit": 0, "credit": 100},
        ],
    )
    aid = action_id(env, ENTRY)
    url = f"/apps/accounting/action/{aid}/{move_id}"
    token = csrf_from(admin, url)
    response = admin.post(
        f"{url}/button/action_post", data={"csrf_token": token}, follow_redirects=True
    )
    assert response.status_code == 200
    assert env["accounting.move"].read([move_id])[0]["state"] == "posted"
    assert "Entry posted as" in response.get_data(as_text=True)


def test_internal_user_reads_but_cannot_write(app: Application, env, registry):
    limited = Env(
        app.db,
        registry=registry,
        uid=2,
        user={
            "id": 2,
            "login": "viewer",
            "is_admin": False,
            "group_xmlids": ["base.group_user"],
            "company_id": 1,
        },
    )
    assert limited["accounting.move"].search([])
    with pytest.raises(Exception, match="cannot create"):
        limited["accounting.move"].create(
            {
                "move_type": "entry",
                "journal_id": _journal(env, "GEN"),
                "date": dt.date.today(),
                "company_id": 1,
            }
        )


def test_new_invoice_form_inherits_the_action_domain(admin: Client, env):
    aid = action_id(env, INVOICE)
    token = csrf_from(admin, "/apps")
    response = admin.post(
        "/web/rpc",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "view.form",
            "params": {"app": "accounting", "action_id": aid, "id": None},
        },
        headers={"X-CSRF-Token": token},
    )
    result = response.get_json()["result"]
    assert result["record"]["move_type"] == "out_invoice"


def test_posted_form_withholds_the_save_control(admin: Client, env):
    move_id = _move(
        env,
        line_ids=[
            {"account_id": _account(env, "1010"), "name": "Cash", "debit": 100, "credit": 0},
            {"account_id": _account(env, "4000"), "name": "Income", "debit": 0, "credit": 100},
        ],
    )
    invoke(env, "accounting.move", "action_post", move_id)
    aid = action_id(env, ENTRY)
    page = admin.get(f"/apps/accounting/action/{aid}/{move_id}").get_data(as_text=True)
    assert 'class="btn btn-primary" type="submit">Save' not in page
    assert "Reverse" in page
