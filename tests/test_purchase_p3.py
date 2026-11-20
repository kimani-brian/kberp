"""P3: agreements, approvals, analysis and landed costs."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from kberp.addons.inventory.services import api as inventory_api
from kberp.addons.inventory.services import valuation
from kberp.addons.purchase.handlers import reminders
from kberp.addons.purchase.services import agreements, analysis, landed_costs
from kberp.addons.purchase.services import orders as purchase_orders
from kberp.env import Env
from kberp.orm.model import ValidationError
from kberp.web.app import Application


def _vendor(env: Env) -> int:
    return env["core.partner"].search([("name", "=", "Demo Supplier")], limit=1)[0]


def _product(env: Env) -> int:
    return env["core.product_template"].search(
        [("name", "=", "Warehouse Pallet")], limit=1
    )[0]


def _order(env: Env, qty: float = 500, partner_id: int | None = None) -> int:
    return env["purchase.order"].create(
        {
            "partner_id": partner_id or _vendor(env),
            "company_id": 1,
            "order_line": [
                {
                    "product_id": _product(env),
                    "name": "Warehouse Pallet",
                    "qty": qty,
                    "price_unit": 900,
                }
            ],
        }
    )


def _buyer(env: Env) -> Env:
    groups = ["base.group_user", "purchase.group_purchase_user"]
    user_id = env["core.user"].create(
        {
            "name": f"Buyer {uuid.uuid4().hex[:6]}",
            "login": f"buyer-{uuid.uuid4().hex[:8]}",
            "company_id": 1,
            "group_xmlids": groups,
        }
    )
    return Env(
        env.db,
        registry=env.registry,
        uid=user_id,
        user={
            "id": user_id,
            "login": "buyer",
            "is_admin": False,
            "company_id": 1,
            "group_xmlids": groups,
        },
    )


def test_agreement_call_off_never_exceeds_the_balance(env):
    agreement_ids = env["purchase.agreement"].search([], limit=1)
    assert agreement_ids
    agreement = env["purchase.agreement"].read([agreement_ids[0]])[0]
    line = agreement["line_ids"][0]
    assert line["qty"] == 1000

    order_id = agreements.call_off(
        env, agreement_ids[0], [{"agreement_line_id": line["id"], "qty": 200}]
    )
    line_row = env["purchase.agreement_line"].read([line["id"]])[0]
    assert line_row["qty_called"] == 200
    assert line_row["qty_remaining"] == 800

    with pytest.raises(ValidationError):
        agreements.call_off(
            env, agreement_ids[0], [{"agreement_line_id": line["id"], "qty": 900}]
        )
    order = env["purchase.order"].read([order_id])[0]
    assert order["agreement_id"]["id"] == agreement_ids[0]
    assert order["origin"].startswith("AGREEMENT/")


def test_approval_is_enforced_for_a_buyer_and_a_manager_can_approve(env):
    order_id = _order(env, qty=500)
    buyer = _buyer(env)
    result = purchase_orders.confirm(buyer, order_id)
    assert result["approval_state"] == "waiting"
    order = env["purchase.order"].read([order_id])[0]
    assert order["state"] == "draft"
    assert not env["inventory.picking"].search([("origin", "=", order["name"])])

    with pytest.raises(ValidationError):
        buyer["purchase.order"].write([order_id], {"state": "purchase"})

    approved = purchase_orders.approve(env, order_id)
    assert approved["state"] == "purchase"
    order = env["purchase.order"].read([order_id])[0]
    assert order["approval_state"] == "approved"
    assert env["inventory.picking"].search([("origin", "=", order["name"])])


def test_landed_cost_raises_stock_value_and_posts_a_balanced_entry(app: Application, env):
    product = _product(env)
    with app.db.transaction():
        picking = inventory_api.create_receipt(
            env,
            origin=f"P3/LC/{uuid.uuid4().hex[:8]}",
            partner_id=_vendor(env),
            company_id=1,
            lines=[{"product_id": product, "name": "Pallet", "qty": 4}],
        )
        inventory_api.validate(env, picking)
        valuation.value_picking(env, picking)
    before = valuation.stock_value(env)
    cost_id = env["purchase.landed_cost"].create(
        {
            "picking_id": picking,
            "vendor_id": _vendor(env),
            "date": dt.date.today(),
            "split_method": "by_quantity",
            "company_id": 1,
            "line_ids": [{"name": "Freight", "amount": 120}],
        }
    )
    with app.db.transaction():
        result = landed_costs.post_landed_cost(env, cost_id)
    assert result["state"] == "posted"
    assert valuation.stock_value(env) == before + 120
    cost = env["purchase.landed_cost"].read([cost_id])[0]
    entry = env["accounting.move"].read([cost["valuation_move_id"]["id"]])[0]
    assert entry["state"] == "posted"
    assert entry["amount_debit"] == entry["amount_credit"] == 120


def test_analysis_totals_reconcile_with_confirmed_order_lines(env):
    order_id = _order(env, qty=10)
    env.with_context(allow_confirmed=True)["purchase.order"].write(
        [order_id], {"state": "purchase", "date_order": dt.datetime.now(dt.UTC)}
    )
    analysis_id = env["purchase.analysis"].search([], limit=1)[0]
    order = env["purchase.order"].read([order_id])[0]
    expected = order["amount_untaxed"]
    analysis.run(env, analysis_id)
    rows = env["purchase.analysis"].read([analysis_id])[0]["line_ids"]
    assert rows
    total = sum(row["amount"] for row in rows)
    confirmed = env["purchase.order"].search([("state", "=", "purchase")])
    assert total == pytest.approx(
        sum(row["amount_untaxed"] for row in env["purchase.order"].read(confirmed))
    )
    assert total >= expected


def test_receipt_reminder_runs_once_per_day(env):
    order_id = _order(env, qty=1)
    env.with_context(allow_confirmed=True)["purchase.order"].write(
        [
            order_id
        ],
        {
            "state": "purchase",
            "date_order": dt.datetime.now(dt.UTC),
            "expected_date": dt.date.today() - dt.timedelta(days=1),
        },
    )
    first = reminders.send_receipt_reminders(env)
    second = reminders.send_receipt_reminders(env)
    assert first >= 1
    assert second == 0
