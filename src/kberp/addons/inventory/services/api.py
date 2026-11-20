"""Public inventory API used by Sales, Purchase and the inventory screens.

Only IDs and plain values cross this boundary. The caller owns the transaction,
so a validation and its quant changes commit or roll back together.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....orm.model import ValidationError
from ....services.events import emit

OPERATION_CODES = {
    "in": "WH/IN",
    "out": "WH/OUT",
    "internal": "WH/INT",
}


def _settings(env, company_id: int | None = None) -> dict[str, Any]:
    domain = [("company_id", "=", int(company_id))] if company_id else []
    ids = env["inventory.settings"].search(domain, limit=1)
    if not ids:
        ids = env["inventory.settings"].search([], limit=1)
    return env["inventory.settings"].read([ids[0]])[0] if ids else {}


def _operation(env, code: str) -> dict[str, Any]:
    operation_code = OPERATION_CODES[code]
    ids = env["inventory.operation_type"].search([("code", "=", operation_code)], limit=1)
    if not ids:
        raise ValidationError(f"operation type {operation_code} is not configured")
    return env["inventory.operation_type"].read([ids[0]])[0]


def _location_id(value: Any) -> int | None:
    if not value:
        return None
    return value["id"] if isinstance(value, dict) else int(value)


def _location_tree(env, location_id: int) -> list[int]:
    """A location and every descendant, for reservation and availability."""
    ids = [int(location_id)]
    frontier = [int(location_id)]
    while frontier:
        children = env["inventory.location"].search([("parent_id", "in", frontier)])
        children = [child for child in children if child not in ids]
        ids.extend(children)
        frontier = children
    return ids


def available_qty(env, product_id: int, location_id: int) -> float:
    """Free quantity for a product in a location and its children."""
    locations = _location_tree(env, location_id)
    ids = env["inventory.quant"].search(
        [("product_id", "=", product_id), ("location_id", "in", locations)]
    )
    return sum(
        max(float(row["qty"]) - float(row["reserved_qty"]), 0)
        for row in env["inventory.quant"].read(ids)
    )


def _create_picking(
    env,
    *,
    code: str,
    origin: str,
    lines: list[dict[str, Any]],
    company_id: int | None,
    partner_id: int | None = None,
    scheduled_date: dt.date | None = None,
    source_location_id: int | None = None,
    dest_location_id: int | None = None,
    backorder_id: int | None = None,
) -> int:
    operation = _operation(env, code)
    sequence_ids = operation.get("sequence_id")
    sequence_id = _location_id(sequence_ids)
    if not sequence_id:
        raise ValidationError(f"operation {operation['name']} has no sequence")
    sequence_model: Any = env["core.ir_sequence"]
    sequence = sequence_model.read([sequence_id])[0]
    name = sequence_model.next_code(sequence["xml_id"])
    source = source_location_id or _location_id(operation.get("source_location_id"))
    destination = dest_location_id or _location_id(operation.get("dest_location_id"))
    moves = [
        {
            "product_id": line.get("product_id"),
            "name": line.get("name") or "Operation",
            "qty": line.get("qty", 0),
            "uom_id": line.get("uom_id"),
            "lot_id": line.get("lot_id"),
            "package_id": line.get("package_id"),
            "source_location_id": source,
            "dest_location_id": destination,
            "note": line.get("note") or "",
        }
        for line in lines
        if line.get("product_id")
    ]
    return env["inventory.picking"].create(
        {
            "name": name,
            "origin": origin,
            "picking_type": code,
            "operation_type_id": operation["id"],
            "partner_id": partner_id,
            "source_location_id": source,
            "dest_location_id": destination,
            "company_id": company_id,
            "scheduled_date": scheduled_date,
            "state": "draft",
            "backorder_id": backorder_id,
            "move_ids": moves,
        }
    )


def create_receipt(
    env,
    *,
    origin: str,
    partner_id: int | None,
    company_id: int | None,
    lines: list[dict[str, Any]],
    scheduled_date: dt.date | None = None,
) -> int:
    """Create a draft receipt from a supplier into the warehouse."""
    return _create_picking(
        env,
        code="in",
        origin=origin,
        partner_id=partner_id,
        company_id=company_id,
        lines=lines,
        scheduled_date=scheduled_date,
    )


def create_delivery(
    env,
    *,
    origin: str,
    partner_id: int,
    company_id: int | None,
    lines: list[dict[str, Any]],
    scheduled_date: dt.date | None = None,
) -> int:
    """Create one draft delivery for a document and return its id.

    Repeating the call for the same `origin` returns the existing delivery, which
    keeps order confirmation idempotent.
    """
    pickings = env["inventory.picking"]
    existing = pickings.search(
        [("origin", "=", origin), ("picking_type", "=", "out")], limit=1
    )
    if existing:
        return existing[0]
    return _create_picking(
        env,
        code="out",
        origin=origin,
        partner_id=partner_id,
        company_id=company_id,
        lines=lines,
        scheduled_date=scheduled_date,
    )


def create_internal(
    env,
    *,
    origin: str,
    company_id: int | None,
    lines: list[dict[str, Any]],
    source_location_id: int,
    dest_location_id: int,
    scheduled_date: dt.date | None = None,
) -> int:
    """Create a draft internal transfer between two locations."""
    return _create_picking(
        env,
        code="internal",
        origin=origin,
        partner_id=None,
        company_id=company_id,
        lines=lines,
        scheduled_date=scheduled_date,
        source_location_id=source_location_id,
        dest_location_id=dest_location_id,
    )


def reserve(env, picking_id: int) -> int:
    """Allocate source quants to every move, oldest first, and lock them.

    Idempotent: a move that already has detailed lines keeps them. Returns the
    number of detailed lines created.
    """
    pickings = env["inventory.picking"]
    rows = pickings.read([picking_id])
    if not rows:
        raise ValidationError("transfer not found")
    picking = rows[0]
    if picking["state"] in ("done", "cancel"):
        raise ValidationError(f"cannot reserve a {picking['state']} transfer")
    quant_model: Any = env["inventory.quant"]
    move_model = env["inventory.move"]
    line_model = env["inventory.move_line"]
    allow_negative = bool(_settings(env, _location_id(picking.get("company_id"))).get(
        "allow_negative_stock"
    ))
    created = 0
    for move in move_model.read([line["id"] for line in picking.get("move_ids", [])]):
        if move.get("move_line_ids"):
            continue
        demand = float(move["qty"]) - float(move.get("done_qty") or 0)
        if demand <= 0:
            continue
        source = _location_id(move.get("source_location_id")) or _location_id(
            picking.get("source_location_id")
        )
        destination = _location_id(move.get("dest_location_id")) or _location_id(
            picking.get("dest_location_id")
        )
        if not source or not destination:
            raise ValidationError("source and destination locations are required")
        if picking["picking_type"] == "in":
            line_model.create(
                {
                    "move_id": move["id"],
                    "product_id": move["product_id"]["id"],
                    "source_location_id": source,
                    "dest_location_id": destination,
                    "qty": demand,
                    "uom_id": _location_id(move.get("uom_id")),
                    "lot_id": _location_id(move.get("lot_id")),
                    "package_id": _location_id(move.get("package_id")),
                }
            )
            created += 1
            continue
        locations = _location_tree(env, source)
        quant_ids = quant_model.search(
            [
                ("product_id", "=", move["product_id"]["id"]),
                ("location_id", "in", locations),
            ],
            order="id",
        )
        if quant_ids:
            quant_model.lock(quant_ids)
        remaining = demand
        for quant in quant_model.read(quant_ids):
            if remaining <= 0:
                break
            free = float(quant["qty"]) - float(quant["reserved_qty"])
            if free <= 0:
                continue
            taken = min(free, remaining)
            quant_model.write([quant["id"]], {"reserved_qty": float(quant["reserved_qty"]) + taken})
            line_model.create(
                {
                    "move_id": move["id"],
                    "product_id": move["product_id"]["id"],
                    "quant_id": quant["id"],
                    "source_location_id": quant["location_id"]["id"],
                    "dest_location_id": destination,
                    "qty": taken,
                    "uom_id": _location_id(move.get("uom_id")),
                    "lot_id": _location_id(move.get("lot_id")),
                    "package_id": _location_id(move.get("package_id")),
                }
            )
            remaining -= taken
            created += 1
        if remaining > 0 and not allow_negative:
            raise ValidationError(
                f"not enough stock for {move['name']}: {remaining:g} unreserved"
            )
        if remaining > 0:
            line_model.create(
                {
                    "move_id": move["id"],
                    "product_id": move["product_id"]["id"],
                    "source_location_id": source,
                    "dest_location_id": destination,
                    "qty": remaining,
                    "uom_id": _location_id(move.get("uom_id")),
                    "lot_id": _location_id(move.get("lot_id")),
                    "package_id": _location_id(move.get("package_id")),
                }
            )
            created += 1
    if created:
        pickings.write([picking_id], {"state": "assigned"})
    return created


def set_done(env, move_id: int, qty: float) -> None:
    """Set the done quantity on a move, creating a single detailed line."""
    move_model = env["inventory.move"]
    rows = move_model.read([move_id])
    if not rows:
        raise ValidationError("move not found")
    move = rows[0]
    lines = move.get("move_line_ids") or []
    if lines:
        env["inventory.move_line"].write([lines[0]["id"]], {"qty": float(qty)})
    else:
        env["inventory.move_line"].create(
            {
                "move_id": move_id,
                "product_id": move["product_id"]["id"],
                "source_location_id": _location_id(move.get("source_location_id")),
                "dest_location_id": _location_id(move.get("dest_location_id")),
                "qty": float(qty),
                "uom_id": _location_id(move.get("uom_id")),
                "lot_id": _location_id(move.get("lot_id")),
                "package_id": _location_id(move.get("package_id")),
            }
        )


def _quant(env, product_id: int, location_id: int, company_id: int | None) -> int:
    ids = env["inventory.quant"].search(
        [("product_id", "=", product_id), ("location_id", "=", location_id)], limit=1
    )
    if ids:
        return ids[0]
    return env["inventory.quant"].create(
        {
            "product_id": product_id,
            "location_id": location_id,
            "qty": 0,
            "reserved_qty": 0,
            "company_id": company_id,
        }
    )


def validate(env, picking_id: int, *, backorder: bool = True) -> dict[str, Any]:
    """Apply a transfer to quants atomically and optionally create a backorder."""
    pickings = env["inventory.picking"]
    rows = pickings.read([picking_id])
    if not rows:
        raise ValidationError("transfer not found")
    picking = rows[0]
    if picking["state"] in ("done", "cancel"):
        raise ValidationError(f"cannot validate a {picking['state']} transfer")
    if not picking.get("move_ids"):
        raise ValidationError("add at least one operation before validating")
    quant_model: Any = env["inventory.quant"]
    move_model = env["inventory.move"]
    line_model = env["inventory.move_line"]
    company_id = _location_id(picking.get("company_id"))
    allow_negative = bool(_settings(env, company_id).get("allow_negative_stock"))
    if picking["picking_type"] != "in":
        reserve(env, picking_id)
    else:
        for move in move_model.read([line["id"] for line in picking.get("move_ids", [])]):
            if move.get("move_line_ids"):
                continue
            line_model.create(
                {
                    "move_id": move["id"],
                    "product_id": move["product_id"]["id"],
                    "source_location_id": _location_id(move.get("source_location_id")),
                    "dest_location_id": _location_id(move.get("dest_location_id")),
                    "qty": float(move["qty"]),
                    "uom_id": _location_id(move.get("uom_id")),
                    "lot_id": _location_id(move.get("lot_id")),
                    "package_id": _location_id(move.get("package_id")),
                }
            )

    backorder_lines: list[dict[str, Any]] = []
    for move in move_model.read([line["id"] for line in picking.get("move_ids", [])]):
        detail = line_model.read([line["id"] for line in move.get("move_line_ids", [])])
        done = sum(float(line["qty"]) for line in detail)
        if done <= 0:
            continue
        for line in detail:
            source = _location_id(line.get("source_location_id")) or _location_id(
                move.get("source_location_id")
            )
            destination = _location_id(line.get("dest_location_id")) or _location_id(
                move.get("dest_location_id")
            )
            if not source or not destination:
                raise ValidationError("source and destination locations are required")
            qty = float(line["qty"])
            quant_id = _location_id(line.get("quant_id"))
            source_location = env["inventory.location"].read([source])[0]
            virtual_source = source_location["usage"] in (
                "supplier",
                "customer",
                "inventory",
                "production",
                "transit",
            )
            if not virtual_source:
                source_quant = quant_id or _quant(
                    env, move["product_id"]["id"], source, company_id
                )
                quant_model.lock([source_quant])
                quant = quant_model.read([source_quant])[0]
                free = float(quant["qty"]) - float(quant["reserved_qty"])
                if qty > free and not allow_negative:
                    raise ValidationError(
                        f"insufficient stock for {move['name']}: {free:g} available, {qty:g} done"
                    )
                quant_model.write(
                    [source_quant],
                    {
                        "qty": float(quant["qty"]) - qty,
                        "reserved_qty": max(float(quant["reserved_qty"]) - qty, 0),
                    },
                )
            dest_quant_id = _quant(env, move["product_id"]["id"], destination, company_id)
            dest = quant_model.read([dest_quant_id])[0]
            quant_model.write([dest_quant_id], {"qty": float(dest["qty"]) + qty})
        move_model.write([move["id"]], {"done_qty": done})
        remaining = float(move["qty"]) - done
        if remaining > 0:
            backorder_lines.append(
                {
                    "product_id": move["product_id"]["id"],
                    "name": move["name"],
                    "qty": remaining,
                    "uom_id": _location_id(move.get("uom_id")),
                    "lot_id": _location_id(move.get("lot_id")),
                    "package_id": _location_id(move.get("package_id")),
                }
            )
    if backorder and backorder_lines:
        _create_picking(
            env,
            code=picking["picking_type"],
            origin=f"{picking['origin']}-BO",
            lines=backorder_lines,
            company_id=company_id,
            partner_id=_location_id(picking.get("partner_id")),
            scheduled_date=dt.date.today(),
            source_location_id=_location_id(picking.get("source_location_id")),
            dest_location_id=_location_id(picking.get("dest_location_id")),
            backorder_id=picking_id,
        )
    pickings.write([picking_id], {"state": "done"})
    emit(
        env,
        "inventory.picking.validated",
        {"picking_id": picking_id, "company_id": company_id, "origin": picking["origin"]},
    )
    return {"ok": True, "message": "Transfer validated.", "state": "done"}


def cancel(env, picking_id: int) -> dict[str, Any]:
    """Cancel a transfer and release any reservation it holds."""
    pickings = env["inventory.picking"]
    rows = pickings.read([picking_id])
    if not rows:
        raise ValidationError("transfer not found")
    picking = rows[0]
    if picking["state"] == "done":
        raise ValidationError("a done transfer cannot be cancelled")
    quant_model: Any = env["inventory.quant"]
    for move in env["inventory.move"].read([line["id"] for line in picking.get("move_ids", [])]):
        for line in env["inventory.move_line"].read(
            [row["id"] for row in move.get("move_line_ids", [])]
        ):
            quant_id = _location_id(line.get("quant_id"))
            if not quant_id:
                continue
            quant = quant_model.read([quant_id])[0]
            quant_model.write(
                [quant_id],
                {"reserved_qty": max(float(quant["reserved_qty"]) - float(line["qty"]), 0)},
            )
    pickings.write([picking_id], {"state": "cancel"})
    return {"ok": True, "message": "Transfer cancelled.", "state": "cancel"}


def reconcile(env) -> list[dict[str, Any]]:
    """Compare every quant with the sum of done move lines into and out of it."""
    expected: dict[tuple[int | None, int | None], float] = {}
    picking_ids = env["inventory.picking"].search([("state", "=", "done")])
    for picking in env["inventory.picking"].read(picking_ids):
        for move in env["inventory.move"].read([row["id"] for row in picking.get("move_ids", [])]):
            for line in env["inventory.move_line"].read(
                [row["id"] for row in move.get("move_line_ids", [])]
            ):
                if float(line["qty"]) <= 0:
                    continue
                product = _location_id(move.get("product_id"))
                source = _location_id(line.get("source_location_id"))
                destination = _location_id(line.get("dest_location_id"))
                key: tuple[int | None, int | None]
                if product and source:
                    key = (product, source)
                    expected[key] = expected.get(key, 0) - float(line["qty"])
                if product and destination:
                    key = (product, destination)
                    expected[key] = expected.get(key, 0) + float(line["qty"])
    differences: list[dict[str, Any]] = []
    for quant in env["inventory.quant"].read(env["inventory.quant"].search([])):
        key = (
            quant["product_id"]["id"] if quant.get("product_id") else None,
            quant["location_id"]["id"] if quant.get("location_id") else None,
        )
        actual = float(quant["qty"])
        if abs(actual - expected.get(key, 0)) > 0.0001:
            differences.append(
                {"product_id": key[0], "location_id": key[1], "expected": expected.get(key, 0), "actual": actual}
            )
    return differences


def count_documents(env, partner_id: int, company_id: int | None = None) -> int:
    """Transfer count for a contact smart button."""
    domain: list[Any] = [("partner_id", "=", partner_id)]
    if company_id:
        domain.append(("company_id", "=", company_id))
    return env["inventory.picking"].search_count(domain)


def cancel_deliveries(env, *, origin: str) -> int:
    """Cancel every non-done delivery linked to a document."""
    pickings = env["inventory.picking"]
    ids = pickings.search(
        [("origin", "=", origin), ("picking_type", "=", "out"), ("state", "!=", "done")]
    )
    for picking_id in ids:
        cancel(env, picking_id)
    return len(ids)


def cancel_receipts(env, *, origin: str) -> int:
    """Cancel every non-done receipt linked to a document."""
    pickings = env["inventory.picking"]
    ids = pickings.search(
        [("origin", "=", origin), ("picking_type", "=", "in"), ("state", "!=", "done")]
    )
    for picking_id in ids:
        cancel(env, picking_id)
    return len(ids)
