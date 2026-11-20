"""S1: quotations, pricing, transitions and the delivery hand-off."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import action_id, csrf_from, login
from werkzeug.test import Client

from kberp.env import Env
from kberp.orm.model import ConflictError, ValidationError
from kberp.services.actions import invoke

QUOTATION = "sales.action_quotation"


@pytest.fixture()
def admin(client):
    return login(client)


def _product(env: Env) -> int:
    return env["core.product_template"].search([], limit=1)[0]


def _tax(env: Env, name: str = "VAT 16%") -> int:
    return env["accounting.tax"].search([("name", "=", name)], limit=1)[0]


def _create_order(env: Env, **overrides):
    values = {"partner_id": 1, **overrides}
    return env["sales.order"].create(values)


def _line(product_id: int, qty=2, price=2500, discount=0, taxes=None):
    return {
        "product_id": product_id,
        "name": "Warehouse Pallet",
        "qty": qty,
        "price_unit": price,
        "discount": discount,
        "tax_ids": taxes or [],
    }


def test_create_defaults_come_from_the_customer(env):
    order_id = _create_order(env)
    order = env["sales.order"].read([order_id])[0]

    assert order["name"].startswith("SO/")
    assert order["partner_id"]["id"] == 1
    assert order["state"] == "draft"
    assert order["currency_id"]["id"]
    assert order["company_id"]["id"]
    assert order["validity_date"] > dt.date.today()
    assert order["salesperson_id"]
    assert order["invoice_address_id"]
    assert order["delivery_address_id"]


def test_sequence_never_reuses_a_number(env):
    first = env["sales.order"].read([_create_order(env)])[0]["name"]
    second = env["sales.order"].read([_create_order(env)])[0]["name"]
    assert first != second
    assert int(first.rsplit("/", 1)[1]) + 1 == int(second.rsplit("/", 1)[1])


def test_totals_round_per_currency_and_group_taxes(env):
    product = _product(env)
    vat = _tax(env)
    zero = _tax(env, "Zero rated")
    order_id = _create_order(
        env,
        order_line=[
            _line(product, qty=2, price=2500, discount=5, taxes=[vat]),
            _line(product, qty=1, price=999.99, taxes=[vat, zero]),
        ],
    )
    order = env["sales.order"].read([order_id])[0]

    first = round(2500 * 2 * 0.95, 2)
    second = round(999.99, 2)
    assert float(order["amount_untaxed"]) == round(first + second, 2)
    assert float(order["amount_tax"]) == round((first + second) * 0.16, 2)
    assert float(order["amount_total"]) == round(round(first + second, 2) * 1.16, 2)
    assert [float(line["subtotal"]) for line in order["order_line"]] == [first, second]


def test_confirm_creates_one_delivery_and_emits_an_event(env):
    order_id = _create_order(env, order_line=[_line(_product(env))])
    result = invoke(env, "sales.order", "action_confirm", order_id)
    assert result["state"] == "sale"

    order = env["sales.order"].read([order_id])[0]
    assert order["state"] == "sale"
    assert order["date_order"]
    picking_ids = env["inventory.picking"].search([("origin", "=", order["name"])])
    assert len(picking_ids) == 1
    picking = env["inventory.picking"].read(picking_ids)[0]
    assert picking["state"] == "draft"
    assert len(picking["move_ids"]) == 1

    events = env["platform.outbox_event"].search(
        [("event_type", "=", "sales.order.confirmed")]
    )
    assert events
    assert json.loads(env["platform.outbox_event"].read([events[-1]])[0]["payload"])[
        "order_id"
    ] == order_id

    messages = env["chatter.message"].search(
        [("model", "=", "sales.order"), ("res_id", "=", order_id)]
    )
    assert any("confirmed" in row["body"] for row in env["chatter.message"].read(messages))


def test_confirm_is_idempotent_by_origin(env):
    product = _product(env)
    first = _create_order(env, order_line=[_line(product)])
    second = _create_order(env, order_line=[_line(product)])
    invoke(env, "sales.order", "action_confirm", first)
    invoke(env, "sales.order", "action_confirm", second)
    origins = [
        row["origin"]
        for row in env["inventory.picking"].read(env["inventory.picking"].search([]))
    ]
    assert len(origins) == len(set(origins))


def test_confirm_rejects_a_second_transition(env):
    order_id = _create_order(env, order_line=[_line(_product(env))])
    invoke(env, "sales.order", "action_confirm", order_id)
    with pytest.raises(ConflictError, match="cannot confirm"):
        invoke(env, "sales.order", "action_confirm", order_id)


def test_confirm_needs_at_least_one_line(env):
    order_id = _create_order(env)
    with pytest.raises(ValidationError, match="at least one order line"):
        invoke(env, "sales.order", "action_confirm", order_id)


def test_delivery_failure_rolls_the_whole_confirmation_back(env, monkeypatch):
    from kberp.addons.sales.services import orders

    order_id = _create_order(env, order_line=[_line(_product(env))])

    def broken(*args, **kwargs):
        raise RuntimeError("warehouse offline")

    monkeypatch.setattr(orders, "create_delivery", broken)
    with pytest.raises(RuntimeError, match="warehouse offline"):
        invoke(env, "sales.order", "action_confirm", order_id)
    order = env["sales.order"].read([order_id])[0]
    assert order["state"] == "draft"
    assert not env["inventory.picking"].search([("origin", "=", order["name"])])


def test_cancel_cancels_the_delivery_and_reset_reopens(env):
    order_id = _create_order(env, order_line=[_line(_product(env))])
    invoke(env, "sales.order", "action_confirm", order_id)
    order = env["sales.order"].read([order_id])[0]
    picking = env["inventory.picking"].search([("origin", "=", order["name"])])[0]

    invoke(env, "sales.order", "action_cancel", order_id)
    assert env["inventory.picking"].read([picking])[0]["state"] == "cancel"
    with pytest.raises(ConflictError, match="cannot cancel"):
        invoke(env, "sales.order", "action_cancel", order_id)

    invoke(env, "sales.order", "action_reset", order_id)
    assert env["sales.order"].read([order_id])[0]["state"] == "draft"


def test_lines_can_be_replaced_in_one_write(env):
    product = _product(env)
    order_id = _create_order(env, order_line=[_line(product)])
    first_line = env["sales.order"].read([order_id])[0]["order_line"][0]["id"]
    env["sales.order"].write(
        [order_id],
        {"order_line": [{"id": first_line, "qty": 3}, _line(product, qty=1)]},
    )
    lines = env["sales.order"].read([order_id])[0]["order_line"]
    assert len(lines) == 2
    assert [float(line["qty"]) for line in lines] == [3.0, 1.0]
    assert float(env["sales.order"].read([order_id])[0]["amount_untaxed"]) == 4 * 2500


def test_quotation_list_and_form_render_the_document_ui(admin: Client, env):
    aid = action_id(env, QUOTATION)
    order_id = _create_order(env, order_line=[_line(_product(env))])

    listing = admin.get(f"/apps/sales/action/{aid}").get_data(as_text=True)
    assert "Quotations" in listing
    assert order_name(env, order_id) in listing

    form = admin.get(f"/apps/sales/action/{aid}/{order_id}").get_data(as_text=True)
    assert 'class="status-bar"' in form
    assert "status-active" in form
    assert 'class="line-editor"' in form
    assert 'name="order_line[' in form
    assert 'formaction="' in form
    assert "Totals" in form


def order_name(env: Env, order_id: int) -> str:
    return env["sales.order"].read([order_id])[0]["name"]


def test_button_post_confirms_and_reports_the_result(admin: Client, env):
    aid = action_id(env, QUOTATION)
    order_id = _create_order(env, order_line=[_line(_product(env))])
    url = f"/apps/sales/action/{aid}/{order_id}"
    token = csrf_from(admin, url)
    response = admin.post(
        f"{url}/button/action_confirm",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert env["sales.order"].read([order_id])[0]["state"] == "sale"
    assert "Sales order confirmed" in response.get_data(as_text=True)


def test_json_rpc_button_returns_the_refreshed_form(admin: Client, env):
    aid = action_id(env, QUOTATION)
    order_id = _create_order(env, order_line=[_line(_product(env))])
    token = csrf_from(admin, "/apps")
    response = admin.post(
        "/web/rpc",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "object.action",
            "params": {
                "app": "sales",
                "action_id": aid,
                "id": order_id,
                "name": "action_confirm",
            },
        },
        headers={"X-CSRF-Token": token},
    )
    result = response.get_json()["result"]
    assert result["state"] == "sale"
    assert result["record_id"] == order_id
    assert result["record"]["state"] == "sale"
    assert "buttons" in result["spec"]


def test_send_writes_a_mail_attachment_and_the_report_renders(
    admin: Client, env, tmp_path, monkeypatch
):
    monkeypatch.setenv("KB_MAIL_DIR", str(tmp_path))
    tax = _tax(env)
    order_id = _create_order(
        env,
        note="Payment within 14 days.",
        order_line=[_line(_product(env), taxes=[tax])],
    )
    result = invoke(env, "sales.order", "action_send", order_id)
    assert result["state"] == "sent"

    message_file = tmp_path / result["message_file"]
    assert message_file.exists()
    import json

    payload = json.loads(message_file.read_text())
    assert payload["subject"].startswith("Quotation SO/")
    assert "Warehouse Pallet" in payload["attachment"]["html"]
    assert "Payment within 14 days." in payload["attachment"]["html"]

    from kberp.addons.sales.services.reports import quotation_html

    html = quotation_html(env, order_id)
    assert "VAT 16%" in html
    assert "Payment within 14 days." in html

    aid = action_id(env, QUOTATION)
    response = admin.get(f"/apps/sales/action/{aid}/{order_id}/report/quotation")
    assert response.status_code == 200
    assert "Quotation SO/" in response.get_data(as_text=True) or "SO/" in response.get_data(as_text=True)


def test_form_offers_a_preview_link(admin: Client, env):
    aid = action_id(env, QUOTATION)
    order_id = _create_order(env, order_line=[_line(_product(env))])
    form = admin.get(f"/apps/sales/action/{aid}/{order_id}").get_data(as_text=True)
    assert "/report/quotation" in form
    assert "Preview" in form
