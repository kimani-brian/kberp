"""S2: delivered quantities, invoicing queues, guards and lock state."""

from __future__ import annotations

import uuid

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.addons.inventory.services import api as stock
from kberp.addons.sales.services import fulfillment
from kberp.env import Env
from kberp.orm.model import ValidationError
from kberp.services.actions import invoke
from kberp.web.app import Application

TO_INVOICE = "sales.action_to_invoice"
UPSELL = "sales.action_upsell"


@pytest.fixture()
def admin(client):
    return login(client)


def _product(env: Env) -> int:
    return env["core.product_template"].search([], limit=1)[0]


def _order(env: Env, qty: float = 2, policy: str = "delivered") -> int:
    return env["sales.order"].create(
        {
            "partner_id": 1,
            "invoice_policy": policy,
            "order_line": [
                {
                    "product_id": _product(env),
                    "name": "Pallet",
                    "qty": qty,
                    "price_unit": 1000,
                }
            ],
        }
    )


def _pickings(env: Env, order_id: int):
    order = env["sales.order"].read([order_id])[0]
    return env["inventory.picking"].search([("origin", "=", order["name"])])


def _deliver(env: Env, order_id: int, qty: float) -> None:
    receipt = stock.create_receipt(
        env,
        origin=f"TEST/S2/RECEIPT/{uuid.uuid4().hex[:8]}",
        partner_id=1,
        company_id=1,
        lines=[{"product_id": _product(env), "name": "Pallet", "qty": qty}],
    )
    stock.validate(env, receipt)
    picking_id = _pickings(env, order_id)[0]
    move = env["inventory.move"].read(
        env["inventory.move"].search([("picking_id", "=", picking_id)])
    )[0]
    stock.set_done(env, move["id"], qty)
    stock.validate(env, picking_id)
    fulfillment.recompute(env, [order_id])


def test_partial_delivery_sets_to_invoice_and_invoice_quantities(app: Application, env):
    order_id = _order(env, qty=2)
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
        _deliver(env, order_id, 1)
    fulfillment.recompute(env, [order_id])
    row = env["sales.order"].read([order_id])[0]
    assert row["qty_delivered"] == 1
    assert row["invoice_status"] == "to invoice"
    line = row["order_line"][0]
    assert line["qty_delivered"] == 1

    result = invoke(env, "sales.order", "action_invoice", order_id)
    invoice = env["accounting.move"].read([result["invoice_id"]])[0]
    assert invoice["state"] == "draft"
    assert invoice["origin"] == row["name"]
    product_line = next(line for line in invoice["line_ids"] if line["kind"] == "product")
    assert product_line["qty"] == 1
    fulfillment.recompute(env, [order_id])
    assert env["sales.order"].read([order_id])[0]["qty_invoiced"] == 1


def test_posting_an_invoice_completes_the_order(app: Application, env):
    order_id = _order(env, qty=2)
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
        _deliver(env, order_id, 2)
    invoice_id = invoke(env, "sales.order", "action_invoice", order_id)["invoice_id"]
    with app.db.transaction():
        invoke(env, "accounting.move", "action_post", invoice_id)
    fulfillment.recompute(env, [order_id])
    row = env["sales.order"].read([order_id])[0]
    assert row["qty_invoiced"] == 2
    assert row["invoice_status"] == "fully invoiced"
    with pytest.raises(ValidationError, match="nothing left to invoice"):
        invoke(env, "sales.order", "action_invoice", order_id)


def test_ordered_policy_invoices_the_full_order_after_partial_delivery(app: Application, env):
    order_id = _order(env, qty=4, policy="ordered")
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
        _deliver(env, order_id, 1)
    invoice_id = invoke(env, "sales.order", "action_invoice", order_id)["invoice_id"]
    line = next(
        row
        for row in env["accounting.move"].read([invoice_id])[0]["line_ids"]
        if row["kind"] == "product"
    )
    assert line["qty"] == 4


def test_over_invoicing_marks_upselling(app: Application, env):
    from kberp.addons.accounting.services.api import create_invoice

    order_id = _order(env, qty=1)
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
    name = env["sales.order"].read([order_id])[0]["name"]
    invoice_id = create_invoice(
        env,
        partner_id=1,
        company_id=1,
        origin=name,
        lines=[{"product_id": _product(env), "name": "Pallet", "qty": 3, "price_unit": 1000}],
    )
    with app.db.transaction():
        invoke(env, "accounting.move", "action_post", invoice_id)
    fulfillment.recompute(env, [order_id])
    assert env["sales.order"].read([order_id])[0]["invoice_status"] == "upselling"


def test_locked_order_rejects_writes_and_unlock_restores_editing(app: Application, env):
    order_id = _order(env)
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
    assert invoke(env, "sales.order", "action_lock", order_id)["locked"] is True
    with pytest.raises(ValidationError, match="is locked"):
        env["sales.order"].write([order_id], {"reference": "changed"})
    assert invoke(env, "sales.order", "action_unlock", order_id)["locked"] is False
    env["sales.order"].write([order_id], {"reference": "changed"})
    assert env["sales.order"].read([order_id])[0]["reference"] == "changed"


def test_event_handlers_are_idempotent(app: Application, env):
    order_id = _order(env, qty=2)
    with app.db.transaction():
        invoke(env, "sales.order", "action_confirm", order_id)
        _deliver(env, order_id, 1)
    from kberp.addons.sales.handlers.events import on_delivered

    payload = {"origin": env["sales.order"].read([order_id])[0]["name"]}
    on_delivered(env, payload)
    first = env["sales.order"].read([order_id])[0]["qty_delivered"]
    on_delivered(env, payload)
    assert env["sales.order"].read([order_id])[0]["qty_delivered"] == first == 1
    assert env["accounting.audit_log"].search([]) is not None


def test_queues_and_form_controls_are_available(admin: Client, env):
    page = admin.get("/apps/sales").get_data(as_text=True)
    assert "To Invoice" in page
    assert "Orders to Upsell" in page

    order_id = _order(env)
    with app_transaction(env):
        invoke(env, "sales.order", "action_confirm", order_id)
    aid = action_id(env, TO_INVOICE)
    listing = admin.get(f"/apps/sales/action/{aid}").get_data(as_text=True)
    assert "Orders to Invoice" in listing
    form = admin.get(f"/apps/sales/action/{aid}/{order_id}").get_data(as_text=True)
    assert "Create Invoice" in form
    assert "Lock" in form


def app_transaction(env: Env):
    return env.db.transaction()
