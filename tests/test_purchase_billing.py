"""P2: receipt feedback, bills, three-way match and lock state."""

from __future__ import annotations

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.inventory.services import api as stock
from kberp.addons.purchase.services import billing
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
    return env["purchase.vendor_price"].read(
        env["purchase.vendor_price"].search([], limit=1)
    )[0]["product_id"]["id"]


def _order(env: Env, qty: float = 100, policy: str = "received"):
    return env["purchase.order"].create(
        {
            "partner_id": _vendor(env),
            "bill_control": policy,
            "order_line": [{"product_id": _product(env), "name": "Pallet", "qty": qty}],
        }
    )


def _confirmed(env: Env, qty: float = 100, policy: str = "received"):
    order_id = _order(env, qty, policy)
    invoke(env, "purchase.order", "action_confirm", order_id)
    return order_id


def _open_pickings(env: Env, order_id: int):
    name = env["purchase.order"].read([order_id])[0]["name"]
    return env["inventory.picking"].search(
        [
            "|",
            ("origin", "=", name),
            ("origin", "like", f"{name}-BO%"),
            ("state", "in", ["draft", "assigned"]),
        ]
    )


def _receive(env: Env, order_id: int, qty: float):
    picking_id = _open_pickings(env, order_id)[0]
    move = env["inventory.move"].read(
        env["inventory.move"].search([("picking_id", "=", picking_id)])
    )[0]
    stock.set_done(env, move["id"], qty)
    stock.validate(env, picking_id)
    billing.recompute(env, [order_id])


def test_partial_receipt_updates_qty_and_status(app: Application, env):
    order_id = _confirmed(env)
    with app.db.transaction():
        _receive(env, order_id, 40)
    row = env["purchase.order"].read([order_id])[0]
    assert row["qty_received"] == 40
    assert row["receipt_status"] == "partial"
    assert row["order_line"][0]["qty_received"] == 40


def test_bill_control_blocks_billing_when_nothing_is_received(env):
    order_id = _confirmed(env)
    with pytest.raises(ValidationError, match="nothing received"):
        invoke(env, "purchase.order", "action_create_bill", order_id)


def test_receive_bill_and_complete_the_chain(app: Application, env):
    order_id = _confirmed(env)
    with app.db.transaction():
        _receive(env, order_id, 40)
    result = invoke(env, "purchase.order", "action_create_bill", order_id)
    bill = env["accounting.move"].read([result["bill_id"]])[0]
    line = next(row for row in bill["line_ids"] if row["kind"] == "product")
    assert line["qty"] == 40
    assert bill["move_type"] == "in_invoice"
    with app.db.transaction():
        invoke(env, "accounting.move", "action_post", result["bill_id"])
    billing.recompute(env, [order_id])
    row = env["purchase.order"].read([order_id])[0]
    assert row["qty_billed"] == 40
    assert row["invoice_status"] == "waiting"

    with app.db.transaction():
        _receive(env, order_id, 60)
    row = env["purchase.order"].read([order_id])[0]
    assert row["receipt_status"] == "full"
    assert row["qty_received"] == 100

    result = invoke(env, "purchase.order", "action_create_bill", order_id)
    with app.db.transaction():
        invoke(env, "accounting.move", "action_post", result["bill_id"])
    billing.recompute(env, [order_id])
    row = env["purchase.order"].read([order_id])[0]
    assert row["qty_billed"] == 100
    assert row["invoice_status"] == "full"

    with pytest.raises(ValidationError, match="nothing left to bill"):
        invoke(env, "purchase.order", "action_create_bill", order_id)


def test_ordered_policy_bills_the_full_order_after_any_receipt(app: Application, env):
    order_id = _confirmed(env, qty=10, policy="ordered")
    with app.db.transaction():
        _receive(env, order_id, 1)
    result = invoke(env, "purchase.order", "action_create_bill", order_id)
    line = next(
        row
        for row in env["accounting.move"].read([result["bill_id"]])[0]["line_ids"]
        if row["kind"] == "product"
    )
    assert line["qty"] == 10


def test_event_recompute_is_idempotent(app: Application, env):
    order_id = _confirmed(env)
    with app.db.transaction():
        _receive(env, order_id, 25)
    from kberp.addons.purchase.handlers.events import on_receipt_validated

    name = env["purchase.order"].read([order_id])[0]["name"]
    on_receipt_validated(env, {"origin": name})
    first = env["purchase.order"].read([order_id])[0]["qty_received"]
    on_receipt_validated(env, {"origin": name})
    assert env["purchase.order"].read([order_id])[0]["qty_received"] == first == 25


def test_locked_order_rejects_writes_but_unlock_restores(env):
    order_id = _confirmed(env)
    assert invoke(env, "purchase.order", "action_lock", order_id)["locked"]
    with pytest.raises(ValidationError, match="is locked"):
        env["purchase.order"].write([order_id], {"reference": "changed"})
    assert not invoke(env, "purchase.order", "action_unlock", order_id)["locked"]
    env["purchase.order"].write([order_id], {"reference": "changed"})
    assert env["purchase.order"].read([order_id])[0]["reference"] == "changed"


def test_three_way_match_columns_and_buttons_render(admin: Client, env):
    order_id = _confirmed(env)
    aid = action_id(env, RFQ)
    form = admin.get(f"/apps/purchase/action/{aid}/{order_id}").get_data(as_text=True)
    assert "Received" in form
    assert "Billed" in form
    assert "Create Bill" in form
    assert "Lock" in form
