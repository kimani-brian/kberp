"""Replenishment, putaway and barcode helpers."""

from __future__ import annotations

import math
from typing import Any

from ....env import Env
from ....orm.model import ValidationError
from . import api

ORIGIN_PREFIX = "REORDER/"


def incoming_qty(env: Env, product_id: int, location_id: int) -> float:
    """Quantity already on its way to a location in open transfers."""
    picking_model = env["inventory.picking"]
    open_ids = picking_model.search([("state", "in", ["draft", "assigned"])])
    if not open_ids:
        return 0.0
    move_model = env["inventory.move"]
    move_ids = move_model.search(
        [
            ("picking_id", "in", open_ids),
            ("product_id", "=", product_id),
            ("dest_location_id", "=", location_id),
        ]
    )
    return sum(float(row["qty"]) for row in move_model.read(move_ids))


def replenish(env: Env, point_ids: list[int]) -> list[int]:
    """Create at most one RFQ per triggered orderpoint and return their ids."""
    from ....addons.purchase.services.api import create_rfq, preferred_vendor

    created = []
    points = env["inventory.orderpoint"]
    for point in points.read(point_ids):
        if not point["active"]:
            continue
        product = (point.get("product_id") or {}).get("id")
        location = (point.get("location_id") or {}).get("id")
        if not product or not location:
            continue
        on_hand = api.available_qty(env, product, location)
        inbound = incoming_qty(env, product, location)
        shortfall = float(point["min_qty"]) - (on_hand + inbound)
        if shortfall <= 0:
            continue
        if point.get("last_rfq_id"):
            existing = env["purchase.order"].search(
                [("id", "=", point["last_rfq_id"]["id"]), ("state", "=", "draft")]
            )
            if existing:
                continue
        multiple = float(point.get("qty_multiple") or 1) or 1
        qty = math.ceil(shortfall / multiple) * multiple
        maximum = float(point.get("max_qty") or 0)
        if maximum > 0:
            qty = min(qty, maximum)
        vendor = preferred_vendor(env, product)
        if not vendor:
            raise ValidationError(
                f"no vendor price available for {point['name']}, so no RFQ was created"
            )
        origin = f"{ORIGIN_PREFIX}{point['name']}"
        rfq_id = create_rfq(
            env,
            partner_id=vendor,
            company_id=(point.get("company_id") or {}).get("id"),
            lines=[{"product_id": product, "name": point["name"], "qty": qty}],
            origin=origin,
        )
        points.write([point["id"]], {"last_rfq_id": rfq_id})
        created.append(rfq_id)
    return created


def scheduler(env: Env) -> list[int]:
    """Run every active orderpoint once."""
    ids = env["inventory.orderpoint"].search([("active", "=", True)])
    return replenish(env, ids)


def putaway_location(env: Env, product_id: int, category_id: int | None = None) -> int | None:
    """Return the suggested location for a product from the first matching rule."""
    rules = env["inventory.putaway_rule"].search([("active", "=", True)], order="sequence, id")
    for rule in env["inventory.putaway_rule"].read(rules):
        if rule.get("product_id") and rule["product_id"]["id"] == product_id:
            return rule["location_id"]["id"]
        if (
            category_id
            and rule.get("category_id")
            and rule["category_id"]["id"] == category_id
        ):
            return rule["location_id"]["id"]
    return None


def parse_barcode(env: Env, code: str) -> dict[str, Any]:
    """Parse a scanned code into a product, optional lot and quantity."""
    nomenclature = env["inventory.barcode_nomenclature"].search(
        [("active", "=", True)], limit=1
    )
    config = (
        env["inventory.barcode_nomenclature"].read([nomenclature[0]])[0]
        if nomenclature
        else {"prefix": "", "lot_separator": "L", "qty_separator": "Q"}
    )
    text = (code or "").strip()
    prefix = config.get("prefix") or ""
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :]
    lot_sep = config.get("lot_separator") or "L"
    qty_sep = config.get("qty_separator") or "Q"
    lot_name = None
    qty = 1.0
    if qty_sep in text:
        text, _, qty_text = text.partition(qty_sep)
        try:
            qty = float(qty_text)
        except ValueError:
            raise ValidationError(f"invalid barcode quantity in {code!r}") from None
    if lot_sep in text:
        text, _, lot_name = text.partition(lot_sep)
    products = env["core.product_template"]
    ids = products.search(["|", ("barcode", "=", text), ("name", "=", text)], limit=1)
    if not ids:
        raise ValidationError(f"unknown barcode {code!r}")
    product = products.read([ids[0]])[0]
    lot_id = None
    if lot_name:
        lot_ids = env["inventory.lot"].search(
            [("name", "=", lot_name), ("product_id", "=", ids[0])], limit=1
        )
        if not lot_ids:
            lot_ids = [
                env["inventory.lot"].create(
                    {"name": lot_name, "product_id": ids[0], "company_id": product.get("company_id") and product["company_id"]["id"]}
                )
            ]
        lot_id = lot_ids[0]
    return {"product_id": ids[0], "name": product["name"], "qty": qty, "lot_id": lot_id}


def scan(env: Env, picking_id: int, code: str) -> dict[str, Any]:
    """Add a scanned line to a picking, or increase an existing one."""
    parsed = parse_barcode(env, code)
    picking = env["inventory.picking"].read([picking_id])
    if not picking:
        raise ValidationError("transfer not found")
    moves = env["inventory.move"]
    existing = moves.search(
        [("picking_id", "=", picking_id), ("product_id", "=", parsed["product_id"])], limit=1
    )
    if existing:
        row = moves.read([existing[0]])[0]
        moves.write([existing[0]], {"qty": float(row["qty"]) + parsed["qty"]})
        move_id = existing[0]
    else:
        move_id = moves.create(
            {
                "picking_id": picking_id,
                "product_id": parsed["product_id"],
                "name": parsed["name"],
                "qty": parsed["qty"],
                "lot_id": parsed["lot_id"],
            }
        )
    return {"ok": True, "move_id": move_id, **parsed}
