"""Object buttons for counts and scrap."""

from __future__ import annotations

from ....env import Env
from ....services.actions import object_action
from . import api, audit

MODEL = "inventory.picking"


@object_action(MODEL, "action_check")
def check(env: Env, picking_id: int):
    created = api.reserve(env, picking_id)
    return {
        "ok": True,
        "message": "Availability checked." if created else "Already reserved.",
        "state": "assigned",
    }


@object_action(MODEL, "action_validate")
def validate(env: Env, picking_id: int):
    return api.validate(env, picking_id)


@object_action(MODEL, "action_cancel")
def cancel(env: Env, picking_id: int):
    return api.cancel(env, picking_id)




@object_action("inventory.stock_count", "action_validate")
def validate_count(env: Env, record_id: int):
    return audit.validate_count(env, record_id)


@object_action("inventory.scrap", "action_validate")
def validate_scrap(env: Env, record_id: int):
    return audit.validate_scrap(env, record_id)


@object_action("inventory.orderpoint", "action_replenish")
def replenish_point(env: Env, record_id: int):
    from .procurement import replenish

    ids = replenish(env, [record_id])
    return {
        "ok": True,
        "message": "RFQ created." if ids else "Stock is already sufficient.",
        "rfq_ids": ids,
    }
