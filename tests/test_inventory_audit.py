"""I2: counts, scrap, lots, packages and traceability."""

from __future__ import annotations

import uuid

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.inventory.services import api, audit
from kberp.env import Env
from kberp.services.actions import invoke
from kberp.web.app import Application

COUNT = "inventory.action_count"
SCRAP = "inventory.action_scrap"


@pytest.fixture()
def admin(client):
    return login(client)


def _new_product(env: Env) -> int:
    return env["core.product_template"].create(
        {"name": f"Tracked {uuid.uuid4().hex[:8]}", "list_price": 10, "standard_price": 5}
    )


def _stock_location(env: Env) -> int:
    return env["inventory.location"].search([("usage", "=", "internal")], limit=1)[0]


def _receive(env: Env, product: int, qty: float, lot: int | None = None):
    return api.create_receipt(
        env,
        origin=f"I2/RECEIPT/{uuid.uuid4().hex[:8]}",
        partner_id=1,
        company_id=1,
        lines=[{"product_id": product, "name": "Tracked item", "qty": qty, "lot_id": lot}],
    )


def test_count_corrects_the_quant_and_records_an_adjustment(app: Application, env):
    product = _new_product(env)
    location = _stock_location(env)
    with app.db.transaction():
        api.validate(env, _receive(env, product, 10))
    count_id = env["inventory.stock_count"].create(
        {
            "location_id": location,
            "company_id": 1,
            "line_ids": [
                {"product_id": product, "expected_qty": 10, "counted_qty": 8}
            ],
        }
    )
    result = invoke(env, "inventory.stock_count", "action_validate", count_id)
    assert result["adjustments"] == 1
    assert env["inventory.stock_count"].read([count_id])[0]["state"] == "done"
    assert api.available_qty(env, product, location) == 8
    lines = env["inventory.count_line"].read(
        env["inventory.count_line"].search([("count_id", "=", count_id)])
    )
    assert lines[0]["difference"] == -2
    assert env["platform.outbox_event"].search([("event_type", "=", "inventory.count.validated")])


def test_scrap_reduces_stock_and_emits_a_valuation_payload(app: Application, env):
    product = _new_product(env)
    location = _stock_location(env)
    with app.db.transaction():
        api.validate(env, _receive(env, product, 5))
    scrap_id = env["inventory.scrap"].create(
        {"product_id": product, "qty": 1, "location_id": location, "reason": "Damaged", "company_id": 1}
    )
    result = invoke(env, "inventory.scrap", "action_validate", scrap_id)
    assert result["state"] == "done"
    assert api.available_qty(env, product, location) == 4
    events = env["platform.outbox_event"].search([("event_type", "=", "inventory.scrap.validated")])
    assert events
    payload = env["platform.outbox_event"].read([events[-1]])[0]["payload"]
    assert "Damaged" in payload
    assert '"qty": 1' in payload


def test_lot_uniqueness_and_traceability(app: Application, env):
    product = _new_product(env)
    lot = env["inventory.lot"].create({"name": "SN-1", "product_id": product, "company_id": 1})
    with pytest.raises(Exception, match="uniq"):
        env["inventory.lot"].create({"name": "SN-1", "product_id": product, "company_id": 1})
    with app.db.transaction():
        api.validate(env, _receive(env, product, 2, lot))
        delivery = api.create_delivery(
            env,
            origin=f"I2/DELIVERY/{uuid.uuid4().hex[:8]}",
            partner_id=1,
            company_id=1,
            lines=[{"product_id": product, "name": "Tracked item", "qty": 1, "lot_id": lot}],
        )
        api.validate(env, delivery)
    chain = audit.traceability(env, lot)
    assert {row["type"] for row in chain} == {"in", "out"}
    assert any(row["qty"] == 2 for row in chain)
    assert any(row["qty"] == 1 for row in chain)


def test_package_is_carried_on_move_lines(env):
    product = _new_product(env)
    package_type = env["inventory.package_type"].create({"name": "Carton"})
    package = env["inventory.package"].create(
        {"name": "PKG-1", "package_type_id": package_type, "company_id": 1}
    )
    picking_id = _receive(env, product, 12)
    move = env["inventory.move"].read(
        env["inventory.move"].search([("picking_id", "=", picking_id)])
    )[0]
    env["inventory.move"].write([move["id"]], {"package_id": package})
    with env.db.transaction():
        api.validate(env, picking_id)
    line = env["inventory.move_line"].read(
        env["inventory.move_line"].search([("move_id", "=", move["id"])])
    )[0]
    assert line["package_id"]["id"] == package


def test_audit_screens_are_available(admin: Client, env):
    page = admin.get("/apps/inventory").get_data(as_text=True)
    for label in ("Physical Inventory", "Scrap", "Lots / Serial Numbers", "Moves History", "Traceability"):
        assert label in page
    count_id = env["inventory.stock_count"].create(
        {"location_id": _stock_location(env), "line_ids": []}
    )
    form = admin.get(f"/apps/inventory/action/{action_id(env, COUNT)}/{count_id}").get_data(as_text=True)
    assert "Validate Count" in form
    scrap_id = env["inventory.scrap"].create({"product_id": _new_product(env), "qty": 1})
    form = admin.get(f"/apps/inventory/action/{action_id(env, SCRAP)}/{scrap_id}").get_data(as_text=True)
    assert "Validate Scrap" in form
