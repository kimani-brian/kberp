"""Migration importers: dry runs, de-duplication and reconciliation."""

from __future__ import annotations

import datetime as dt

import pytest

from kberp.migration import (
    import_file,
    import_opening_balances,
    import_partners,
    import_products,
    load_csv,
    write_templates,
)


def write_csv(tmp_path, name: str, header: str, rows: list[str]):
    path = tmp_path / name
    path.write_text(header + "\n" + "\n".join(rows) + "\n")
    return path


PARTNER_HEADER = "name,external_id,is_company,email,vat,city,parent_external_id,tags"


def test_partner_dry_run_then_commit_is_idempotent(env, tmp_path):
    path = write_csv(
        tmp_path,
        "partners.csv",
        PARTNER_HEADER,
        [
            "Migration Co,MIG-001,true,hello@migration.test,P1,Nairobi,,Wholesale",
            "Migration Person,MIG-002,false,person@migration.test,,Nairobi,MIG-001,",
        ],
    )

    dry = import_file(env, "partners", path, dry_run=True)
    assert dry.ok, dry.errors
    assert dry.created == 2
    assert env["core.partner"].search_count([("external_id", "=", "MIG-001")]) == 0

    first = import_file(env, "partners", path, dry_run=False)
    assert first.ok, first.errors
    assert first.created == 2
    company = env["core.partner"].search([("external_id", "=", "MIG-001")])
    person = env["core.partner"].read(
        env["core.partner"].search([("external_id", "=", "MIG-002")])
    )[0]
    assert person["parent_id"]["id"] == company[0]

    second = import_file(env, "partners", path, dry_run=False)
    assert second.ok, second.errors
    assert second.updated == 2
    assert second.created == 0
    assert env["core.partner"].search_count([("external_id", "like", "MIG-")]) == 2


def test_partner_rows_report_errors_without_writing(env, tmp_path):
    path = write_csv(
        tmp_path,
        "bad.csv",
        PARTNER_HEADER,
        [
            ",MIG-100,true,,,,",
            "Orphan,MIG-101,false,,,Nairobi,MIG-999,",
        ],
    )
    result = import_file(env, "partners", path, dry_run=True)
    assert not result.ok
    assert any("name is required" in error for error in result.errors)
    assert any("parent external_id" in error for error in result.errors)
    assert env["core.partner"].search_count([("external_id", "like", "MIG-1")]) == 0


def test_products_match_on_default_code(env, tmp_path):
    path = write_csv(
        tmp_path,
        "products.csv",
        "name,external_id,default_code,type,list_price,standard_price",
        ["Migration Widget,MIG-P1,MIG-WIDGET,goods,19.5,10"],
    )
    first = import_products(env, load_csv(path), dry_run=False)
    assert first.created == 1, first.errors
    second = import_products(env, load_csv(path), dry_run=False)
    assert second.updated == 1, second.errors
    assert env["core.product_template"].search_count(
        [("default_code", "=", "MIG-WIDGET")]
    ) == 1


def test_opening_balances_must_balance(env):
    accounts = env["accounting.account"].search([], limit=2)
    assert len(accounts) == 2
    codes = [row["code"] for row in env["accounting.account"].read(accounts)]
    today = dt.date.today().isoformat()
    rows = [
        {"date": today, "account_code": codes[0], "label": "Debit", "debit": "500", "credit": ""},
        {"date": today, "account_code": codes[1], "label": "Credit", "debit": "", "credit": "400"},
    ]
    result = import_opening_balances(env, rows, dry_run=True)
    assert not result.ok
    assert any("do not balance" in error for error in result.errors)
    assert result.totals["debit"] == "500"


def test_opening_balances_post_one_balanced_entry(env):
    accounts = env["accounting.account"].search([], limit=2)
    codes = [row["code"] for row in env["accounting.account"].read(accounts)]
    today = dt.date.today().isoformat()
    rows = [
        {"date": today, "account_code": codes[0], "label": "Opening debit", "debit": "1250", "credit": ""},
        {"date": today, "account_code": codes[1], "label": "Opening credit", "debit": "", "credit": "1250"},
    ]
    result = import_opening_balances(env, rows, dry_run=False)
    assert result.ok, result.errors
    moves = env["accounting.move"].search([("origin", "=", "MIGRATION/OPENING")])
    assert len(moves) == 1
    move = env["accounting.move"].read(moves)[0]
    assert move["state"] == "posted"
    assert float(move["amount_debit"]) == float(move["amount_credit"]) == 1250.0

    again = import_opening_balances(env, rows, dry_run=False)
    assert again.ok
    assert again.skipped == 1


def test_stock_count_import_creates_reviewable_draft(env):
    products = env["core.product_template"].search([], limit=1)
    locations = env["inventory.location"].search([("usage", "=", "internal")], limit=1)
    assert products and locations
    product = env["core.product_template"].read(products)[0]
    code = product.get("default_code") or product["name"]
    location = env["inventory.location"].read(locations)[0]
    rows = [
        {
            "location": location["name"],
            "product_code": code,
            "counted_qty": "7",
        }
    ]
    result = import_file_rows("stock_counts", env, rows)
    assert result.ok, result.errors
    assert result.created == 1
    count_ids = env["inventory.stock_count"].search([], order="-id", limit=1)
    count = env["inventory.stock_count"].read(count_ids)[0]
    assert count["state"] == "draft"
    assert count["line_ids"][0]["counted_qty"] == 7.0


def import_file_rows(kind, env, rows):
    from kberp.migration import import_stock_counts

    return import_stock_counts(env, rows, dry_run=False)


def test_templates_are_written(tmp_path):
    paths = write_templates(tmp_path)
    assert {path.name for path in paths} == {
        "partners.csv",
        "products.csv",
        "opening_balances.csv",
        "stock_counts.csv",
    }
    for path in paths:
        assert path.read_text().splitlines()[0]
        load_csv(path)


def test_unknown_kind_is_rejected(env, tmp_path):
    path = write_csv(tmp_path, "x.csv", "name", ["x"])
    with pytest.raises(Exception):
        import_file(env, "unknown", path)
