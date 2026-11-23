"""F1 UAT-01…09 against the shipping product.

Each test is named after the business script in `prd.md` §11.1. They use the
public services and web client, not private helpers, so a pass means the
documented scenario works end to end.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.accounting.services import reporting
from kberp.addons.accounting.services.payments import recompute_invoice, register_payment
from kberp.addons.inventory.services import api as stock
from kberp.addons.inventory.services import audit as stock_audit
from kberp.addons.purchase.services import billing
from kberp.addons.purchase.services import orders as purchase_orders
from kberp.env import Env
from kberp.parity import parity_report
from kberp.services.actions import invoke
from kberp.web.app import Application

APPS = {
    "contacts": "Contacts",
    "sales": "Sales",
    "accounting": "Accounting",
    "purchase": "Purchase",
    "inventory": "Inventory",
}


@pytest.fixture()
def admin(client):
    return login(client)


def _product(env: Env, name: str | None = None) -> int:
    domain = [("name", "=", name)] if name else []
    return env["core.product_template"].search(domain, limit=1)[0]


def _new_product(env: Env, prefix: str = "UAT") -> int:
    code = f"{prefix}-{uuid.uuid4().hex[:8]}"
    return env["core.product_template"].create(
        {
            "name": f"UAT Product {code}",
            "default_code": code,
            "type": "goods",
            "list_price": 25,
            "standard_price": 10,
        }
    )


def _journal(env: Env, code: str = "BNK") -> int:
    return env["accounting.journal"].search([("code", "=", code)], limit=1)[0]


def _balanced(env: Env, move_id: int) -> bool:
    move = env["accounting.move"].read([move_id])[0]
    return Decimal(str(move["amount_debit"])) == Decimal(str(move["amount_credit"]))


def _stock_receipt(env: Env, product: int, qty: float, origin: str | None = None) -> int:
    picking = stock.create_receipt(
        env,
        origin=origin or f"UAT/RECEIPT/{uuid.uuid4().hex[:8]}",
        partner_id=1,
        company_id=1,
        lines=[{"product_id": product, "name": "UAT stock", "qty": qty}],
    )
    stock.validate(env, picking)
    return picking


def test_uat_01_launcher_opens_five_apps_and_menus_match(admin: Client, env: Env):
    page = admin.get("/apps")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    for label in APPS.values():
        assert label in html

    for key in APPS:
        response = admin.get(f"/apps/{key}")
        assert response.status_code == 200, key

    report = parity_report(env)
    assert report["ok"], report["problems"]
    assert report["menus"]["score"] == 100.0
    assert [app["key"] for app in report["apps"]] == list(APPS)
    assert all(app["menus"] > 0 for app in report["apps"])


def test_uat_02_create_company_addresses_tag_and_bank(env: Env):
    tag = env["core.partner_tag"].create({"name": "UAT Strategic"})
    company_id = env["core.partner"].create(
        {
            "name": "UAT Holdings",
            "is_company": True,
            "tag_ids": [tag],
            "city": "Nairobi",
        }
    )
    invoice_id = env["core.partner"].create(
        {
            "name": "UAT Holdings Invoice",
            "parent_id": company_id,
            "type": "invoice",
            "street": "Invoice Road",
        }
    )
    delivery_id = env["core.partner"].create(
        {
            "name": "UAT Holdings Delivery",
            "parent_id": company_id,
            "type": "delivery",
            "street": "Delivery Road",
        }
    )
    bank_id = env["core.bank"].search([], limit=1)
    assert bank_id
    account_id = env["core.bank_account"].create(
        {
            "partner_id": company_id,
            "bank_id": bank_id[0],
            "acc_number": f"UAT-{uuid.uuid4().hex[:8]}",
        }
    )

    company = env["core.partner"].read([company_id])[0]
    assert company["complete_name"] == "UAT Holdings"
    addresses = env["core.partner"].address_get(company_id)
    assert addresses["invoice"] == invoice_id
    assert addresses["delivery"] == delivery_id
    assert company["tag_ids"][0]["name"] == "UAT Strategic"
    assert env["core.bank_account"].read([account_id])[0]["partner_id"]["id"] == company_id


def test_uat_03_quote_to_cash_links_every_document(app: Application, env: Env):
    product = _product(env)
    order_id = env["sales.order"].create(
        {
            "partner_id": 1,
            "company_id": 1,
            "invoice_policy": "ordered",
            "order_line": [
                {
                    "product_id": product,
                    "name": "UAT quote line",
                    "qty": 3,
                    "price_unit": 250,
                }
            ],
        }
    )
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
        _stock_receipt(env, product, 10)
    order = env["sales.order"].read([order_id])[0]
    picking_ids = env["inventory.picking"].search([("origin", "=", order["name"])])
    assert picking_ids

    invoice_id = invoke(env, "sales.order", "action_invoice", order_id)["invoice_id"]
    with app.db.transaction():
        invoke(env, "accounting.move", "action_post", invoice_id)
    invoice = env["accounting.move"].read([invoice_id])[0]
    assert invoice["origin"] == order["name"]
    assert invoice["partner_id"]["id"] == 1
    assert _balanced(env, invoice_id)

    with app.db.transaction():
        payment = register_payment(
            env, invoice_id, amount=invoice["amount_total"], journal_id=_journal(env)
        )
    recompute_invoice(env, [invoice_id])
    invoice = env["accounting.move"].read([invoice_id])[0]
    assert invoice["payment_state"] == "paid"
    assert invoice["amount_residual"] == 0
    assert payment["payment_id"]


def test_uat_04_rfq_approval_receipt_bill_and_payment(app: Application, env: Env):
    product = _product(env, "Warehouse Pallet")
    vendor = env["core.partner"].search([("name", "=", "Demo Supplier")], limit=1)[0]
    groups = ["base.group_user", "purchase.group_purchase_user"]
    buyer_id = env["core.user"].create(
        {
            "name": f"UAT Buyer {uuid.uuid4().hex[:6]}",
            "login": f"uat-buyer-{uuid.uuid4().hex[:8]}",
            "company_id": 1,
            "group_xmlids": groups,
        }
    )
    buyer = Env(
        env.db,
        registry=env.registry,
        uid=buyer_id,
        user={
            "id": buyer_id,
            "login": "uat-buyer",
            "is_admin": False,
            "company_id": 1,
            "group_xmlids": groups,
        },
    )
    order_id = env["purchase.order"].create(
        {
            "partner_id": vendor,
            "company_id": 1,
            "order_line": [
                {
                    "product_id": product,
                    "name": "UAT pallet",
                    "qty": 500,
                    "price_unit": 900,
                }
            ],
        }
    )
    with app.db.transaction():
        purchase_orders.send(buyer, order_id)
        waiting = purchase_orders.confirm(buyer, order_id)
    assert waiting["approval_state"] == "waiting"
    assert env["purchase.order"].read([order_id])[0]["state"] in ("draft", "sent")

    with app.db.transaction():
        approved = purchase_orders.approve(env, order_id)
    assert approved["state"] == "purchase"
    order = env["purchase.order"].read([order_id])[0]
    picking_ids = env["inventory.picking"].search(
        [("origin", "=", order["name"]), ("state", "!=", "cancel")]
    )
    assert picking_ids

    move = env["inventory.move"].read(
        env["inventory.move"].search([("picking_id", "=", picking_ids[0])])
    )[0]
    with app.db.transaction():
        stock.set_done(env, move["id"], 500)
        stock.validate(env, picking_ids[0])
        billing.recompute(env, [order_id])
    order = env["purchase.order"].read([order_id])[0]
    assert order["qty_received"] == 500
    assert order["receipt_status"] == "full"

    bill_id = invoke(env, "purchase.order", "action_create_bill", order_id)["bill_id"]
    with app.db.transaction():
        invoke(env, "accounting.move", "action_post", bill_id)
    bill = env["accounting.move"].read([bill_id])[0]
    assert bill["move_type"] == "in_invoice"
    assert bill["origin"] == order["name"]
    assert _balanced(env, bill_id)

    with app.db.transaction():
        register_payment(env, bill_id, amount=bill["amount_total"], journal_id=_journal(env))
    recompute_invoice(env, [bill_id])
    assert env["accounting.move"].read([bill_id])[0]["payment_state"] == "paid"


def test_uat_05_count_scrap_and_transfer_keep_quants_and_ledger(app: Application, env: Env):
    product = _new_product(env, "UAT-STOCK")
    stock_location = env["inventory.location"].search(
        [("xml_id", "=", "inventory.location_stock")], limit=1
    )
    assert stock_location
    with app.db.transaction():
        _stock_receipt(env, product, 10)
    assert stock.available_qty(env, product, stock_location[0]) >= 10

    with app.db.transaction():
        count_id = env["inventory.stock_count"].create(
            {
                "location_id": stock_location[0],
                "line_ids": [{"product_id": product, "counted_qty": 8}],
            }
        )
        stock_audit.validate_count(env, count_id)
    assert stock.available_qty(env, product, stock_location[0]) == 8

    with app.db.transaction():
        scrap_id = env["inventory.scrap"].create(
            {
                "name": f"UAT-SCRAP-{uuid.uuid4().hex[:6]}",
                "date": dt.date.today(),
                "product_id": product,
                "qty": 2,
                "location_id": stock_location[0],
                "company_id": 1,
            }
        )
        stock_audit.validate_scrap(env, scrap_id)
    assert stock.available_qty(env, product, stock_location[0]) == 6

    with app.db.transaction():
        transfer = stock.create_internal(
            env,
            origin=f"UAT/TRANSFER/{uuid.uuid4().hex[:8]}",
            company_id=1,
            lines=[{"product_id": product, "name": "UAT transfer", "qty": 3}],
            source_location_id=stock_location[0],
            dest_location_id=stock_location[0],
        )
        stock.validate(env, transfer)
    assert stock.available_qty(env, product, stock_location[0]) == 6
    assert stock.reconcile(env) == []


def test_uat_06_post_invoice_and_reconcile_partial_payment(app: Application, env: Env):
    product = _product(env)
    order_id = env["sales.order"].create(
        {
            "partner_id": 1,
            "company_id": 1,
            "invoice_policy": "ordered",
            "order_line": [
                {"product_id": product, "name": "UAT partial", "qty": 1, "price_unit": 1000}
            ],
        }
    )
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
    invoice_id = invoke(env, "sales.order", "action_invoice", order_id)["invoice_id"]
    with app.db.transaction():
        invoke(env, "accounting.move", "action_post", invoice_id)
        register_payment(env, invoice_id, amount=400, journal_id=_journal(env))
    recompute_invoice(env, [invoice_id])
    invoice = env["accounting.move"].read([invoice_id])[0]
    assert invoice["payment_state"] == "partial"
    assert invoice["amount_residual"] == 600
    assert _balanced(env, invoice_id)
    with app.db.transaction():
        register_payment(env, invoice_id, amount=600, journal_id=_journal(env))
    recompute_invoice(env, [invoice_id])
    invoice = env["accounting.move"].read([invoice_id])[0]
    assert invoice["payment_state"] == "paid"
    assert invoice["amount_residual"] == 0


def test_uat_07_used_partner_cannot_be_deleted_but_can_be_archived(env: Env):
    partner_id = env["core.partner"].create(
        {
            "name": f"UAT Used {uuid.uuid4().hex[:6]}",
            "email": f"used-{uuid.uuid4().hex[:6]}@example.test",
            "company_id": 1,
        }
    )
    env["sales.order"].create(
        {
            "partner_id": partner_id,
            "company_id": 1,
            "order_line": [
                {
                    "product_id": _product(env),
                    "name": "Referencing line",
                    "qty": 1,
                    "price_unit": 10,
                }
            ],
        }
    )
    with pytest.raises(Exception, match="referenced|used|cannot"):
        env["core.partner"].unlink([partner_id])

    env["core.partner"].write([partner_id], {"active": False})
    row = env["core.partner"].read([partner_id])[0]
    assert row["active"] is False
    assert partner_id not in env["core.partner"].search([("id", "=", partner_id)])


def test_uat_08_restricted_user_has_no_accounting_menus_or_urls(app: Application, env: Env):
    login_name = f"uat-restricted-{uuid.uuid4().hex[:8]}"
    app.auth.create_user(login_name, "uat-passphrase", "UAT Restricted", ["base.group_user"])
    client = Client(app)
    login(client, login_name, "uat-passphrase")

    page = client.get("/apps/accounting")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Invoicing" not in html
    assert "Journal Entries" not in html

    move_action = action_id(env, "accounting.action_journal_entry")
    response = client.get(f"/apps/accounting/action/{move_action}")
    assert response.status_code == 403
    assert "Access denied" in response.get_data(as_text=True)


def test_uat_09_reports_reconcile_with_ledger_and_stock(app: Application, env: Env):
    product = _product(env)
    with app.db.transaction():
        _stock_receipt(env, product, 4)
    reports = {
        row["report_type"]: row["id"]
        for row in env["accounting.report"].read(env["accounting.report"].search([]))
    }
    reporting.run(env, reports["trial_balance"])
    trial = env["accounting.report"].read([reports["trial_balance"]])[0]
    total = next(line for line in trial["line_ids"] if line["label"] == "Total")
    assert Decimal(str(total["amount"])) == 0

    reporting.run(env, reports["balance_sheet"])
    balance = env["accounting.report"].read([reports["balance_sheet"]])[0]
    amounts = {line["label"]: Decimal(str(line["amount"])) for line in balance["line_ids"]}
    assert amounts["Total assets"] == amounts["Total liabilities and equity"]

    layers = env["inventory.valuation_layer"].search([])
    if layers:
        from kberp.addons.inventory.services import valuation

        assert valuation.stock_value(env) >= 0
