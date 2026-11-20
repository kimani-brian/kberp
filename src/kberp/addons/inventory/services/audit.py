"""Adjustments, scrap and lot traceability services."""

from __future__ import annotations

from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from ....services.events import emit
from . import api


def _location(env: Env, usage: str) -> int:
    ids = env["inventory.location"].search([("usage", "=", usage)], limit=1)
    if not ids:
        raise ValidationError(f"no location with usage {usage!r}")
    return ids[0]


def validate_count(env: Env, count_id: int) -> dict[str, Any]:
    """Apply a physical count through adjustment pickings and close the sheet."""
    rows = env["inventory.stock_count"].read([count_id])
    if not rows:
        raise ValidationError("count not found")
    count = rows[0]
    if count["state"] == "done":
        raise ValidationError("this count is already done")
    lines = env["inventory.count_line"].read([row["id"] for row in count["line_ids"]])
    adjustments = []
    for line in lines:
        difference = float(line["counted_qty"]) - float(line["expected_qty"])
        env["inventory.count_line"].write([line["id"]], {"difference": difference})
        if abs(difference) < 0.0001:
            continue
        source = _location(env, "inventory") if difference > 0 else count["location_id"]["id"]
        destination = count["location_id"]["id"] if difference > 0 else _location(env, "inventory")
        picking_id = api.create_internal(
            env,
            origin=count["name"],
            company_id=(count.get("company_id") or {}).get("id"),
            lines=[
                {
                    "product_id": line["product_id"]["id"],
                    "name": f"Count adjustment: {line['product_id']['name']}",
                    "qty": abs(difference),
                    "lot_id": (line.get("lot_id") or {}).get("id"),
                }
            ],
            source_location_id=source,
            dest_location_id=destination,
        )
        api.validate(env, picking_id)
        adjustments.append(
            {
                "product_id": line["product_id"]["id"],
                "difference": difference,
                "picking_id": picking_id,
            }
        )
    env["inventory.stock_count"].write([count_id], {"state": "done"})
    emit(
        env,
        "inventory.count.validated",
        {"count_id": count_id, "adjustments": adjustments},
    )
    return {
        "ok": True,
        "message": "Count validated.",
        "state": "done",
        "adjustments": len(adjustments),
    }


def validate_scrap(env: Env, scrap_id: int) -> dict[str, Any]:
    """Move scrapped stock to the inventory loss location."""
    rows = env["inventory.scrap"].read([scrap_id])
    if not rows:
        raise ValidationError("scrap record not found")
    scrap = rows[0]
    if scrap["state"] == "done":
        raise ValidationError("this scrap is already done")
    if float(scrap["qty"]) <= 0:
        raise ValidationError("scrap quantity must be positive")
    source = scrap["location_id"]["id"]
    destination = _location(env, "inventory")
    picking_id = api.create_internal(
        env,
        origin=scrap["name"],
        company_id=(scrap.get("company_id") or {}).get("id"),
        lines=[
            {
                "product_id": scrap["product_id"]["id"],
                "name": f"Scrap: {scrap['reason'] or scrap['product_id']['name']}",
                "qty": scrap["qty"],
                "lot_id": (scrap.get("lot_id") or {}).get("id"),
            }
        ],
        source_location_id=source,
        dest_location_id=destination,
    )
    api.validate(env, picking_id)
    env["inventory.scrap"].write([scrap_id], {"state": "done"})
    payload = {
        "scrap_id": scrap_id,
        "picking_id": picking_id,
        "product_id": scrap["product_id"]["id"],
        "qty": float(scrap["qty"]),
        "location_id": source,
        "reason": scrap.get("reason") or "",
        "user_id": env.uid,
    }
    emit(env, "inventory.scrap.validated", payload)
    return {"ok": True, "message": "Scrap validated.", "state": "done", "picking_id": picking_id}


def traceability(env: Env, lot_id: int) -> list[dict[str, Any]]:
    """Return the full move chain for one lot, oldest first."""
    line_ids = env["inventory.move_line"].search([("lot_id", "=", lot_id)], order="id")
    chain = []
    for line in env["inventory.move_line"].read(line_ids):
        move = line.get("move_id") or {}
        picking = {}
        if move:
            moves = env["inventory.move"].read([move["id"]])
            if moves and moves[0].get("picking_id"):
                picking_id = moves[0]["picking_id"]["id"]
                rows = env["inventory.picking"].read([picking_id])
                picking = rows[0] if rows else {}
        chain.append(
            {
                "move_id": move.get("id"),
                "picking_id": picking.get("id"),
                "name": picking.get("name"),
                "origin": picking.get("origin"),
                "type": picking.get("picking_type"),
                "state": picking.get("state"),
                "qty": line["qty"],
                "from": (line.get("source_location_id") or {}).get("name"),
                "to": (line.get("dest_location_id") or {}).get("name"),
            }
        )
    return chain
