"""Perpetual stock valuation, idempotent per stock move."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from ....services.events import emit
from ...accounting.services.posting import post


def _settings(env: Env) -> dict[str, Any]:
    ids = env["inventory.settings"].search([], limit=1)
    return env["inventory.settings"].read([ids[0]])[0] if ids else {}


def _account_id(value: Any) -> int | None:
    if not value:
        return None
    return value["id"] if isinstance(value, dict) else int(value)


def value_move(env: Env, move_id: int) -> dict[str, Any] | None:
    """Post one balanced valuation entry for a done move, at most once."""
    layer_model: Any = env["inventory.valuation_layer"]
    if layer_model.search([("move_id", "=", move_id)], limit=1):
        return None
    rows = env["inventory.move"].read([move_id])
    if not rows:
        return None
    move = rows[0]
    if float(move.get("done_qty") or 0) <= 0:
        return None
    picking_rows = env["inventory.picking"].read([move["picking_id"]["id"]])
    if not picking_rows:
        return None
    picking = picking_rows[0]
    source = move.get("source_location_id") or {}
    destination = move.get("dest_location_id") or {}
    source_id = source.get("id") if isinstance(source, dict) else source
    dest_id = destination.get("id") if isinstance(destination, dict) else destination
    locations = env["inventory.location"]
    source_usage = locations.read([int(source_id)])[0]["usage"] if source_id else None
    dest_usage = locations.read([int(dest_id)])[0]["usage"] if dest_id else None
    if picking["picking_type"] == "internal" and source_usage == dest_usage == "internal":
        return None
    settings = _settings(env)
    if settings.get("valuation") != "perpetual":
        return None
    stock_id = _account_id(settings.get("stock_account_id"))
    cogs_id = _account_id(settings.get("cogs_account_id"))
    loss_id = _account_id(settings.get("loss_account_id"))
    journal_id = _account_id(settings.get("valuation_journal_id"))
    if not all((stock_id, cogs_id, loss_id, journal_id)):
        raise ValidationError("valuation accounts or journal are not configured")
    product_id = move["product_id"]["id"]
    product = env["core.product_template"].read([product_id])[0]
    qty = float(move["done_qty"])
    value = (Decimal(str(product.get("standard_price") or 0)) * Decimal(str(qty))).quantize(
        Decimal("0.01")
    )
    if value == 0:
        return None
    if picking["picking_type"] == "in":
        kind = "in"
        lines = [
            {"account_id": stock_id, "name": "Stock in", "debit": value, "credit": Decimal(0), "kind": "manual"},
            {"account_id": cogs_id, "name": "Stock in offset", "debit": Decimal(0), "credit": value, "kind": "manual"},
        ]
    else:
        kind = "scrap" if dest_usage in ("inventory", "production") else "out"
        account_id = loss_id if kind == "scrap" else cogs_id
        lines = [
            {"account_id": account_id, "name": "Stock out", "debit": value, "credit": Decimal(0), "kind": "manual"},
            {"account_id": stock_id, "name": "Stock out offset", "debit": Decimal(0), "credit": value, "kind": "manual"},
        ]
    account_move_id = env["accounting.move"].create(
        {
            "move_type": "entry",
            "journal_id": journal_id,
            "date": dt.date.today(),
            "company_id": (picking.get("company_id") or {}).get("id"),
            "origin": picking["name"],
            "note": f"Valuation for {move['name'] or picking['name']}",
            "line_ids": lines,
        }
    )
    post(env, account_move_id)
    layer_id = layer_model.create(
        {
            "move_id": move_id,
            "product_id": product_id,
            "qty": qty,
            "value": value,
            "kind": kind,
            "valuation_move_id": account_move_id,
        }
    )
    emit(
        env,
        "inventory.valuation.created",
        {"move_id": move_id, "layer_id": layer_id, "account_move_id": account_move_id},
    )
    return {"layer_id": layer_id, "account_move_id": account_move_id, "kind": kind}


def value_picking(env: Env, picking_id: int) -> list[dict[str, Any]]:
    """Post valuation for every done move in a picking."""
    rows = env["inventory.picking"].read([picking_id])
    if not rows or rows[0]["state"] != "done":
        return []
    move_ids = env["inventory.move"].search([("picking_id", "=", picking_id)])
    result = []
    for move_id in move_ids:
        valued = value_move(env, move_id)
        if valued:
            result.append(valued)
    return result


def stock_value(env: Env) -> Decimal:
    """Book value of stock from perpetual layers."""
    layers = env["inventory.valuation_layer"]
    total = Decimal(0)
    for row in layers.read(layers.search([])):
        direction = 1 if row["kind"] in ("in", "adjust") else -1
        total += Decimal(str(row["value"])) * direction
    return total
