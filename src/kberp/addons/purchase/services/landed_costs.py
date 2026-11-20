"""Landed cost allocation into stock value and the ledger."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from ...accounting.services.posting import post
from ...inventory.services.valuation import value_picking

EPS = Decimal("0.0001")


def _number(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def _account_id(value: Any) -> int | None:
    if not value:
        return None
    return value["id"] if isinstance(value, dict) else int(value)


def _weights(cost: dict[str, Any], moves: list[dict[str, Any]]) -> list[Decimal]:
    method = cost.get("split_method") or "by_value"
    if method == "equal":
        return [Decimal(1) for _ in moves]
    if method == "by_quantity":
        return [max(_number(move.get("done_qty")), Decimal(0)) for move in moves]
    result = []
    for move in moves:
        product = (move.get("product_id") or {}).get("id")
        price = Decimal(0)
        if product:
            rows = move.get("_product") or []
            price = Decimal(str((rows[0].get("standard_price") if rows else 0) or 0))
        result.append(max(_number(move.get("done_qty")) * price, Decimal(0)))
    return result


def post_landed_cost(env: Env, cost_id: int) -> dict[str, Any]:
    """Allocate a landed cost across a done receipt and post it.

    Preconditions: the cost is draft, its receipt is done and incoming, and the
    valuation and landed-cost accounts exist. Side effects: stock layers rise,
    one balanced entry posts and the cost is marked posted.
    """
    rows = env["purchase.landed_cost"].read([cost_id])
    if not rows:
        raise ValidationError("landed cost not found")
    cost = rows[0]
    if cost["state"] == "posted":
        raise ValidationError("this landed cost is already posted")
    picking_id = (cost.get("picking_id") or {}).get("id")
    if not picking_id:
        raise ValidationError("select a receipt before posting")
    picking = env["inventory.picking"].read([picking_id])[0]
    if picking["state"] != "done" or picking["picking_type"] != "in":
        raise ValidationError("landed costs only apply to a done incoming receipt")
    lines = env["inventory.move"].read(
        env["inventory.move"].search(
            [("picking_id", "=", picking_id), ("done_qty", ">", 0)]
        )
    )
    if not lines:
        raise ValidationError("the receipt has no done quantities to value")
    total = _number(cost.get("amount_total"))
    if total <= 0:
        raise ValidationError("the landed cost has no amount")

    products = env["core.product_template"]
    for move in lines:
        product_id = (move.get("product_id") or {}).get("id")
        move["_product"] = products.read([product_id])[0] if product_id else {}
    weights = _weights(cost, lines)
    weight_total = sum(weights, Decimal(0))
    if weight_total <= 0:
        weights = [Decimal(1) for _ in lines]
        weight_total = Decimal(len(lines))

    # A perpetual receipt already has layers; make sure periodic receipts do too.
    value_picking(env, picking_id)
    layer_model = env["inventory.valuation_layer"]
    allocated: list[Decimal] = []
    remaining = total
    for index, (move, weight) in enumerate(zip(lines, weights, strict=True)):
        share = (
            remaining
            if index == len(lines) - 1
            else (total * weight / weight_total).quantize(Decimal("0.01"))
        )
        remaining -= share
        allocated.append(share)
        layer_ids = layer_model.search([("move_id", "=", move["id"])], limit=1)
        if layer_ids:
            layer = layer_model.read([layer_ids[0]])[0]
            layer_model.write(
                [layer_ids[0]], {"value": _number(layer["value"]) + share}
            )
        else:
            layer_model.create(
                {
                    "move_id": move["id"],
                    "product_id": (move.get("product_id") or {}).get("id"),
                    "qty": 0,
                    "value": share,
                    "kind": "adjust",
                }
            )

    from ...inventory.services.valuation import _settings as inventory_settings

    stock_id = _account_id(inventory_settings(env).get("stock_account_id"))
    settings = env["purchase.settings"].search([], limit=1)
    purchase_settings = (
        env["purchase.settings"].read([settings[0]])[0] if settings else {}
    )
    default_account = (
        _account_id(cost.get("account_id"))
        or _account_id(purchase_settings.get("landed_cost_account_id"))
    )
    if not stock_id or not default_account:
        raise ValidationError("stock and landed-cost accounts are not configured")
    credits: dict[int, Decimal] = {}
    for line in cost.get("line_ids", []):
        account = _account_id(line.get("account_id")) or default_account
        credits[account] = credits.get(account, Decimal(0)) + _number(line["amount"])
    if not credits:
        credits[default_account] = total
    journal_id = _account_id(cost.get("journal_id"))
    if not journal_id:
        journal_ids = env["accounting.journal"].search([("code", "=", "INV")], limit=1)
        journal_id = journal_ids[0] if journal_ids else None
    if not journal_id:
        raise ValidationError("no valuation journal is configured")
    entry_lines = [
        {
            "account_id": stock_id,
            "name": f"Landed cost {cost['name']}",
            "debit": total,
            "credit": Decimal(0),
            "kind": "manual",
        }
    ]
    for account, amount in credits.items():
        if amount == 0:
            continue
        entry_lines.append(
            {
                "account_id": account,
                "name": f"Landed cost {cost['name']}",
                "debit": Decimal(0),
                "credit": amount,
                "kind": "manual",
            }
        )
    entry_id = env["accounting.move"].create(
        {
            "move_type": "entry",
            "journal_id": journal_id,
            "date": cost.get("date") or dt.date.today(),
            "company_id": _account_id(cost.get("company_id")),
            "currency_id": _account_id(cost.get("currency_id")),
            "origin": cost["name"],
            "note": f"Landed cost on {picking['name']}",
            "line_ids": entry_lines,
        }
    )
    post(env, entry_id)
    env["purchase.landed_cost"].write(
        [cost_id], {"state": "posted", "valuation_move_id": entry_id}
    )
    return {
        "ok": True,
        "message": f"Landed cost posted as {env['accounting.move'].read([entry_id])[0]['name']}.",
        "state": "posted",
        "valuation_move_id": entry_id,
        "allocated": [str(value) for value in allocated],
    }
