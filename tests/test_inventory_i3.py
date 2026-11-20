"""I3: replenishment, perpetual valuation, barcodes and configuration."""

from __future__ import annotations

import uuid

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.inventory.services import api, procurement, valuation
from kberp.env import Env
from kberp.web.app import Application

SETTINGS = "inventory.action_inventory_settings"


@pytest.fixture()
def admin(client):
    return login(client)


def _product(env: Env) -> int:
    return env["core.product_template"].search([("name", "=", "Warehouse Pallet")], limit=1)[0]


def _settings(env: Env):
    return env["inventory.settings"].search([], limit=1)[0]


def _receive(env: Env, product: int, qty: float, origin: str | None = None):
    picking = api.create_receipt(
        env,
        origin=origin or f"I3/RECEIPT/{uuid.uuid4().hex[:8]}",
        partner_id=1,
        company_id=1,
        lines=[{"product_id": product, "name": "Pallet", "qty": qty}],
    )
    api.validate(env, picking)
    return picking


def test_configuration_seed(env):
    assert env["inventory.route"].search([("code", "=", "BUY")])
    assert env["inventory.orderpoint"].search([])
    assert env["inventory.barcode_nomenclature"].search([("name", "=", "Default")])
    assert env["inventory.delivery_method"].search([("code", "=", "STD")])
    settings = env["inventory.settings"].read([_settings(env)])[0]
    assert settings["stock_account_id"]
    assert settings["valuation_journal_id"]


def test_scheduler_creates_one_rfq_and_never_duplicates(env):
    first = procurement.scheduler(env)
    second = procurement.scheduler(env)
    assert first and not second
    point = env["inventory.orderpoint"].read(env["inventory.orderpoint"].search([], limit=1))[0]
    assert point["last_rfq_id"]
    rfq = env["purchase.order"].read([point["last_rfq_id"]["id"]])[0]
    assert rfq["origin"].startswith("REORDER/")
    assert rfq["state"] == "draft"


def test_perpetual_valuation_posts_balanced_entries_and_skips_internal(app: Application, env):
    settings_id = _settings(env)
    before = env["inventory.settings"].read([settings_id])[0]["valuation"]
    env["inventory.settings"].write([settings_id], {"valuation": "perpetual"})
    product = _product(env)
    stock_location = env["inventory.location"].search([("usage", "=", "internal")], limit=1)[0]
    try:
        with app.db.transaction():
            picking = _receive(env, product, 2)
            valuation.value_picking(env, picking)
        layer_ids = env["inventory.valuation_layer"].search([("move_id", "!=", False)])
        assert layer_ids
        layer = env["inventory.valuation_layer"].read([layer_ids[-1]])[0]
        assert layer["kind"] == "in"
        entry = env["accounting.move"].read([layer["valuation_move_id"]["id"]])[0]
        assert entry["amount_debit"] == entry["amount_credit"] > 0

        with app.db.transaction():
            internal = api.create_internal(
                env,
                origin=f"I3/INTERNAL/{uuid.uuid4().hex[:8]}",
                company_id=1,
                lines=[{"product_id": product, "name": "Move", "qty": 1}],
                source_location_id=stock_location,
                dest_location_id=stock_location,
            )
            api.validate(env, internal)
            valuation.value_picking(env, internal)
        assert not env["inventory.valuation_layer"].search([("move_id", "in", env["inventory.move"].search([("picking_id", "=", internal)]))])

        with app.db.transaction():
            delivery = api.create_delivery(
                env,
                origin=f"I3/DELIVERY/{uuid.uuid4().hex[:8]}",
                partner_id=1,
                company_id=1,
                lines=[{"product_id": product, "name": "Pallet", "qty": 1}],
            )
            api.validate(env, delivery)
            valuation.value_picking(env, delivery)
        assert valuation.stock_value(env) > 0
    finally:
        env["inventory.settings"].write([settings_id], {"valuation": before})


def test_barcode_parse_and_scan_adds_a_move_line(env):
    product = _product(env)
    env["core.product_template"].write([product], {"barcode": "I3-SCAN"})
    picking = api.create_receipt(
        env,
        origin=f"I3/BARCODE/{uuid.uuid4().hex[:8]}",
        partner_id=1,
        company_id=1,
        lines=[],
    )
    parsed = procurement.parse_barcode(env, "I3-SCANQ3")
    assert parsed["product_id"] == product and parsed["qty"] == 3
    result = procurement.scan(env, picking, "I3-SCANQ3")
    move = env["inventory.move"].read([result["move_id"]])[0]
    assert move["qty"] == 3
    result = procurement.scan(env, picking, "I3-SCANQ2")
    move = env["inventory.move"].read([result["move_id"]])[0]
    assert move["qty"] == 5


def test_putaway_suggestion(env):
    product = _product(env)
    location = procurement.putaway_location(env, product)
    assert location


def test_i3_screens_are_available(admin: Client, env):
    page = admin.get("/apps/inventory").get_data(as_text=True)
    for label in ("Replenishment", "Stock Valuation", "Performance", "Barcode Nomenclatures", "Routes"):
        assert label in page
    settings_id = _settings(env)
    form = admin.get(
        f"/apps/inventory/action/{action_id(env, SETTINGS)}/{settings_id}"
    ).get_data(as_text=True)
    assert "Valuation Journal" in form
    assert "Perpetual" in form

    picking_id = api.create_receipt(
        env,
        origin=f"I3/SCAN FORM/{uuid.uuid4().hex[:8]}",
        partner_id=1,
        company_id=1,
        lines=[],
    )
    form = admin.get(f"/apps/inventory/action/{action_id(env, 'inventory.action_receipt')}/{picking_id}").get_data(as_text=True)
    assert "data-barcode-scan" in form
