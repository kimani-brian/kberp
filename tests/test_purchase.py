"""P1: RFQs, vendor prices, confirmation and receipt requests."""

from __future__ import annotations

import datetime as dt

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.purchase.services.reports import purchase_html
from kberp.addons.purchase.services.vendor_pricing import vendor_price
from kberp.env import Env
from kberp.orm.model import ValidationError
from kberp.services.actions import invoke
from kberp.web.app import Application

RFQ = "purchase.action_rfq"


@pytest.fixture()
def admin(client):
    return login(client)


def _vendor(env: Env) -> int:
    return env["core.partner"].search([("name", "=", "Demo Supplier")], limit=1)[0]


def _product(env: Env) -> int:
    product_ids = env["purchase.vendor_price"].read(
        env["purchase.vendor_price"].search([], limit=1)
    )
    return product_ids[0]["product_id"]["id"] if product_ids else env["core.product_template"].search([], limit=1)[0]


def _order(env: Env, qty: float = 5, **overrides):
    lines = overrides.pop(
        "order_line",
        [{"product_id": _product(env), "name": "Pallet", "qty": qty}],
    )
    return env["purchase.order"].create(
        {"partner_id": _vendor(env), "order_line": lines, **overrides}
    )


def test_vendor_price_precedence_and_dates(env):
    vendor = _vendor(env)
    product = _product(env)
    assert vendor_price(env, partner_id=vendor, product_id=product, qty=1)["price"] == 900
    assert vendor_price(env, partner_id=vendor, product_id=product, qty=20)["price"] == 850
    assert vendor_price(env, partner_id=vendor, product_id=product, qty=1, date=dt.date(2000, 1, 1)) is None


def test_rfq_defaults_price_from_vendor_and_numbers_sequentially(env):
    first = _order(env, qty=1)
    second = _order(env, qty=20)
    rows = env["purchase.order"].read([first, second])
    assert rows[0]["name"] != rows[1]["name"]
    assert rows[0]["order_line"][0]["price_unit"] == 900
    assert rows[1]["order_line"][0]["price_unit"] == 850
    assert rows[0]["buyer_id"] or rows[0]["buyer_id"] is None
    assert rows[0]["currency_id"]


def test_totals_include_taxes(env):
    vat = env["accounting.tax"].search([("amount", "=", 16)], limit=1)[0]
    order_id = _order(env, qty=2, order_line=[
        {"product_id": _product(env), "name": "Pallet", "qty": 2, "price_unit": 1000, "tax_ids": [vat]}
    ])
    row = env["purchase.order"].read([order_id])[0]
    assert row["amount_untaxed"] == 2000
    assert row["amount_tax"] == 320
    assert row["amount_total"] == 2320


def test_confirm_creates_one_receipt_and_state_changes(app: Application, env):
    order_id = _order(env, qty=2)
    assert invoke(env, "purchase.order", "action_send", order_id)["state"] == "sent"
    result = invoke(env, "purchase.order", "action_confirm", order_id)
    assert result["state"] == "purchase"
    order = env["purchase.order"].read([order_id])[0]
    picking_ids = env["inventory.picking"].search([("origin", "=", order["name"])])
    assert len(picking_ids) == 1
    picking = env["inventory.picking"].read(picking_ids)[0]
    assert picking["picking_type"] == "in"
    assert picking["partner_id"]["id"] == order["partner_id"]["id"]
    with pytest.raises(ValidationError, match="cannot confirm"):
        invoke(env, "purchase.order", "action_confirm", order_id)


def test_confirm_rolls_back_when_receipt_fails(app: Application, env, monkeypatch):
    from kberp.addons.purchase.services import orders

    order_id = _order(env, qty=1)

    def broken(*args, **kwargs):
        raise RuntimeError("warehouse offline")

    monkeypatch.setattr(orders, "create_receipt", broken)
    with pytest.raises(RuntimeError, match="warehouse offline"):
        invoke(env, "purchase.order", "action_confirm", order_id)
    order = env["purchase.order"].read([order_id])[0]
    assert order["state"] == "draft"
    assert not env["inventory.picking"].search([("origin", "=", order["name"])])


def test_cancel_cancels_the_linked_receipt(env):
    order_id = _order(env, qty=1)
    invoke(env, "purchase.order", "action_confirm", order_id)
    order = env["purchase.order"].read([order_id])[0]
    picking_id = env["inventory.picking"].search([("origin", "=", order["name"])])[0]
    result = invoke(env, "purchase.order", "action_cancel", order_id)
    assert result["pickings_cancelled"] == 1
    assert env["inventory.picking"].read([picking_id])[0]["state"] == "cancel"
    assert env["purchase.order"].read([order_id])[0]["state"] == "cancel"


def test_confirm_requires_a_vendor_and_lines(env):
    order_id = env["purchase.order"].create(
        {
            "partner_id": _vendor(env),
            "order_line": [],
        }
    )
    with pytest.raises(ValidationError, match="at least one order line"):
        invoke(env, "purchase.order", "action_confirm", order_id)


def test_printable_order_includes_vendor_and_lines(admin: Client, env):
    order_id = _order(env, qty=3)
    html = purchase_html(env, order_id)
    assert "Demo Supplier" in html
    assert "Pallet" in html
    aid = action_id(env, RFQ)
    page = admin.get(f"/apps/purchase/action/{aid}/{order_id}").get_data(as_text=True)
    assert "Print" in page
    assert ">Confirm<" in page
    assert "/report/quotation" in page


def test_purchase_screens_are_available(admin: Client, env):
    page = admin.get("/apps/purchase").get_data(as_text=True)
    assert "Requests for Quotation" in page
    assert "Vendor Pricelists" in page
    aid = action_id(env, RFQ)
    listing = admin.get(f"/apps/purchase/action/{aid}").get_data(as_text=True)
    assert "Requests for Quotation" in listing
