"""I1: warehouses, reservations, validation and quant reconciliation."""

from __future__ import annotations

import uuid

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.inventory.services import api
from kberp.env import Env
from kberp.orm.model import ValidationError
from kberp.services.actions import invoke
from kberp.web.app import Application

RECEIPT = "inventory.action_receipt"
DELIVERY = "inventory.action_delivery"


@pytest.fixture()
def admin(client):
    return login(client)


def _location(env: Env, xml_id: str) -> int:
    return env["inventory.location"].search([("xml_id", "=", xml_id)], limit=1)[0]


def _product(env: Env) -> int:
    return env["core.product_template"].search([], limit=1)[0]


def _new_product(env: Env) -> int:
    return env["core.product_template"].create(
        {"name": f"Stock item {uuid.uuid4().hex[:8]}", "list_price": 10, "standard_price": 5}
    )


def _company(env: Env) -> int:
    return env["core.company"].search([], limit=1)[0]


def _receive(env: Env, qty: float = 100, origin: str | None = None, product: int | None = None) -> int:
    return api.create_receipt(
        env,
        origin=origin or f"TEST/RECEIPT/{uuid.uuid4().hex[:8]}",
        partner_id=1,
        company_id=_company(env),
        lines=[{"product_id": product or _product(env), "name": "Pallet", "qty": qty}],
    )


def _deliver(env: Env, qty: float, origin: str, product: int | None = None) -> int:
    return api.create_delivery(
        env,
        origin=origin,
        partner_id=1,
        company_id=_company(env),
        lines=[{"product_id": product or _product(env), "name": "Pallet", "qty": qty}],
    )


def test_warehouse_locations_and_operations_are_seeded(env):
    warehouse = env["inventory.warehouse"].search([("code", "=", "WH")], limit=1)
    assert warehouse
    codes = {
        row["code"]
        for row in env["inventory.operation_type"].read(
            env["inventory.operation_type"].search([])
        )
    }
    assert codes == {"WH/IN", "WH/OUT", "WH/INT"}
    settings = env["inventory.settings"].read(env["inventory.settings"].search([], limit=1))[0]
    assert settings["allow_negative_stock"] is False


def test_move_requires_a_product(env):
    picking_id = _receive(env)
    with pytest.raises(ValidationError, match="Product is required"):
        env["inventory.move"].create({"picking_id": picking_id, "name": "No product"})


def test_receipt_creates_quant_and_reconciles(app: Application, env):
    with app.db.transaction():
        picking_id = _receive(env)
        api.validate(env, picking_id)
    assert env["inventory.picking"].read([picking_id])[0]["state"] == "done"
    assert api.available_qty(env, _product(env), _location(env, "inventory.location_stock")) == 100
    assert api.reconcile(env) == []
    assert env["platform.outbox_event"].search([("event_type", "=", "inventory.picking.validated")])


def test_reservation_and_negative_stock_guard(app: Application, env):
    product = _new_product(env)
    with app.db.transaction():
        api.validate(env, _receive(env, product=product))
    first = _deliver(env, 60, "TEST/RES-1", product)
    second = _deliver(env, 60, "TEST/RES-2", product)
    assert invoke(env, "inventory.picking", "action_check", first)["ok"]
    with pytest.raises(ValidationError, match="not enough stock"):
        invoke(env, "inventory.picking", "action_check", second)
    assert api.available_qty(env, product, _location(env, "inventory.location_stock")) == 40


def test_negative_done_quantity_is_rejected_and_rolled_back(app: Application, env):
    product = _new_product(env)
    with app.db.transaction():
        api.validate(env, _receive(env, qty=1, product=product))
    with app.db.transaction():
        picking_id = _deliver(env, 10, "TEST/NEG", product)
        move = env["inventory.move"].read(
            env["inventory.move"].search([("picking_id", "=", picking_id)])
        )[0]
        api.set_done(env, move["id"], 50)
        with pytest.raises(ValidationError, match="insufficient stock"):
            api.validate(env, picking_id)
    assert env["inventory.picking"].read([picking_id])[0]["state"] == "draft"
    assert api.available_qty(env, product, _location(env, "inventory.location_stock")) == 1


def test_internal_transfer_keeps_total_on_hand(app: Application, env):
    with app.db.transaction():
        api.validate(env, _receive(env))
    stock = _location(env, "inventory.location_stock")
    before = api.available_qty(env, _product(env), stock)
    with app.db.transaction():
        picking_id = api.create_internal(
            env,
            origin="TEST/INTERNAL",
            company_id=_company(env),
            lines=[{"product_id": _product(env), "name": "Pallet", "qty": 10}],
            source_location_id=stock,
            dest_location_id=stock,
        )
        api.validate(env, picking_id)
    assert api.available_qty(env, _product(env), stock) == before
    assert api.reconcile(env) == []


def test_partial_validation_creates_a_backorder(app: Application, env):
    with app.db.transaction():
        api.validate(env, _receive(env))
    with app.db.transaction():
        picking_id = _deliver(env, 30, "TEST/PARTIAL")
        move = env["inventory.move"].read(
            env["inventory.move"].search([("picking_id", "=", picking_id)])
        )[0]
        api.set_done(env, move["id"], 20)
        api.validate(env, picking_id)
    backorders = env["inventory.picking"].search([("backorder_id", "=", picking_id)])
    assert len(backorders) == 1
    backorder = env["inventory.picking"].read(backorders)[0]
    assert backorder["state"] == "draft"
    assert backorder["origin"] == "TEST/PARTIAL-BO"
    assert api.reconcile(env) == []


def test_done_transfer_is_immutable(app: Application, env):
    with app.db.transaction():
        picking_id = _receive(env, origin="TEST/DONE")
        api.validate(env, picking_id)
    with pytest.raises(ValidationError, match="cannot validate a done"):
        invoke(env, "inventory.picking", "action_validate", picking_id)
    with pytest.raises(ValidationError, match="cannot be edited"):
        env["inventory.picking"].write([picking_id], {"note": "changed"})
    with pytest.raises(ValidationError, match="cannot be cancelled"):
        invoke(env, "inventory.picking", "action_cancel", picking_id)


def test_delivery_uses_customer_location_and_receipt_uses_supplier(env):
    receipt_id = _receive(env, origin="TEST/DIRECTION-IN")
    delivery_id = _deliver(env, 1, "TEST/DIRECTION-OUT")
    rows = env["inventory.picking"].read([receipt_id, delivery_id])
    receipt = next(row for row in rows if row["id"] == receipt_id)
    delivery = next(row for row in rows if row["id"] == delivery_id)
    assert receipt["source_location_id"]["id"] == _location(env, "inventory.location_vendor")
    assert delivery["dest_location_id"]["id"] == _location(env, "inventory.location_customer")


def test_quotation_confirmation_creates_a_delivery(app: Application, env):
    from kberp.web.app import create_app

    web = create_app(app.settings)
    web.db = app.db
    web.registry = app.registry
    values = {
        "partner_id": 1,
        "order_line": [
            {"product_id": _product(env), "name": "Pallet", "qty": 1, "price_unit": 100}
        ],
    }
    with app.db.transaction():
        order_id = web._save_payload(env, action_id(env, "sales.action_quotation"), None, values)
        invoke(env, "sales.order", "action_confirm", order_id)
    order = env["sales.order"].read([order_id])[0]
    pickings = env["inventory.picking"].search([("origin", "=", order["name"])])
    assert len(pickings) == 1
    assert env["inventory.picking"].read(pickings)[0]["picking_type"] == "out"


def test_inventory_shell_and_transfer_screens(admin: Client, env):
    page = admin.get("/apps/inventory").get_data(as_text=True)
    assert "Stock at a glance" in page
    assert "Receipts" in page
    assert "Operations Types" in page

    aid = action_id(env, RECEIPT)
    listing = admin.get(f"/apps/inventory/action/{aid}").get_data(as_text=True)
    assert "Receipts" in listing
    picking_id = _receive(env)
    form = admin.get(f"/apps/inventory/action/{aid}/{picking_id}").get_data(as_text=True)
    assert "Check Availability" in form
    assert "Validate" in form
