"""Blanket agreement call-offs and remaining quantities."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....env import Env
from ....orm.model import ConflictError, ValidationError

EPS = 0.0001


def _read(env: Env, agreement_id: int) -> dict[str, Any]:
    rows = env["purchase.agreement"].read([agreement_id])
    if not rows:
        raise ValidationError("the agreement no longer exists")
    return rows[0]


def recompute_agreement(env: Env, agreement_ids: list[int]) -> None:
    """Rebuild called-off and remaining quantities from live RFQ lines."""
    if not agreement_ids:
        return
    safe = env.with_context(skip_totals=True)
    line_model = safe["purchase.agreement_line"]
    order_line = safe["purchase.order_line"]
    for agreement in safe["purchase.agreement"].read(agreement_ids):
        for line in line_model.read(
            [row["id"] for row in agreement.get("line_ids", [])]
        ):
            order_line_ids = order_line.search(
                [("agreement_line_id", "=", line["id"])]
            )
            called = 0.0
            for row in order_line.read(order_line_ids):
                order = (row.get("order_id") or {}).get("id")
                if not order:
                    continue
                state = safe["purchase.order"].read([order])[0]["state"]
                if state != "cancel":
                    called += float(row["qty"] or 0)
            line_model.write(
                [line["id"]],
                {
                    "qty_called": called,
                    "qty_remaining": max(float(line["qty"] or 0) - called, 0),
                },
            )


def start(env: Env, agreement_id: int) -> dict[str, Any]:
    agreement = _read(env, agreement_id)
    if agreement["state"] != "draft":
        raise ConflictError(f"cannot start a {agreement['state']} agreement")
    today = dt.date.today()
    if agreement["date_end"] < today:
        raise ValidationError("the agreement has already expired")
    env["purchase.agreement"].write([agreement_id], {"state": "running"})
    return {"ok": True, "message": "Agreement is running.", "state": "running"}


def close(env: Env, agreement_id: int) -> dict[str, Any]:
    agreement = _read(env, agreement_id)
    if agreement["state"] not in ("draft", "running"):
        raise ConflictError(f"cannot close a {agreement['state']} agreement")
    env["purchase.agreement"].write([agreement_id], {"state": "closed"})
    return {"ok": True, "message": "Agreement closed.", "state": "closed"}


def cancel(env: Env, agreement_id: int) -> dict[str, Any]:
    agreement = _read(env, agreement_id)
    if agreement["state"] == "cancel":
        raise ConflictError("the agreement is already cancelled")
    env["purchase.agreement"].write([agreement_id], {"state": "cancel"})
    return {"ok": True, "message": "Agreement cancelled.", "state": "cancel"}


def call_off(
    env: Env,
    agreement_id: int,
    lines: list[dict[str, Any]],
) -> int:
    """Create one RFQ linked to an agreement without exceeding its balance.

    Preconditions: the agreement is running and still inside its validity
    window. Side effects: a draft RFQ and recalculated agreement balances.
    """
    agreement = _read(env, agreement_id)
    if agreement["state"] != "running":
        raise ValidationError("start the agreement before calling off quantity")
    today = dt.date.today()
    if today > agreement["date_end"] or today < agreement["date_start"]:
        raise ValidationError("the agreement is outside its validity dates")
    agreement_lines = {
        line["id"]: line for line in agreement.get("line_ids", [])
    }
    order_lines = []
    for line in lines:
        line_id = int(line.get("agreement_line_id") or 0)
        if line_id not in agreement_lines:
            raise ValidationError("pick a line from this agreement")
        source = agreement_lines[line_id]
        qty = float(line.get("qty") or 0)
        if qty <= EPS:
            raise ValidationError("call-off quantity must be positive")
        if qty > float(source.get("qty_remaining") or 0) + EPS:
            raise ValidationError(
                f"call-off of {qty:,.2f} exceeds the remaining "
                f"{float(source.get('qty_remaining') or 0):,.2f} for {source['name']}"
            )
        order_lines.append(
            {
                "product_id": (source.get("product_id") or {}).get("id"),
                "name": source["name"],
                "qty": qty,
                "price_unit": source.get("price_unit") or 0,
                "uom_id": (source.get("uom_id") or {}).get("id"),
                "tax_ids": [tax["id"] for tax in source.get("tax_ids") or []],
                "agreement_line_id": line_id,
            }
        )
    if not order_lines:
        raise ValidationError("add at least one line to call off")
    order_id = env["purchase.order"].create(
        {
            "partner_id": agreement["partner_id"]["id"],
            "agreement_id": agreement_id,
            "origin": f"AGREEMENT/{agreement['name']}",
            "company_id": (agreement.get("company_id") or {}).get("id"),
            "currency_id": (agreement.get("currency_id") or {}).get("id"),
            "order_line": order_lines,
        }
    )
    recompute_agreement(env, [agreement_id])
    return order_id
