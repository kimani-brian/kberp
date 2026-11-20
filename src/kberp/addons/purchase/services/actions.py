"""Object buttons for agreements, landed costs and analysis."""

from __future__ import annotations

from ....env import Env
from ....services.actions import object_action
from . import agreements, analysis, landed_costs


@object_action("purchase.agreement", "action_start")
def start_agreement(env: Env, agreement_id: int):
    return agreements.start(env, agreement_id)


@object_action("purchase.agreement", "action_close")
def close_agreement(env: Env, agreement_id: int):
    return agreements.close(env, agreement_id)


@object_action("purchase.agreement", "action_cancel")
def cancel_agreement(env: Env, agreement_id: int):
    return agreements.cancel(env, agreement_id)


@object_action("purchase.agreement", "action_call_off")
def call_off(env: Env, agreement_id: int):
    rows = env["purchase.agreement"].read([agreement_id])
    if not rows:
        return {"ok": False, "message": "Agreement not found."}
    lines = [
        {"agreement_line_id": line["id"], "qty": line.get("qty_remaining") or 0}
        for line in rows[0].get("line_ids", [])
        if float(line.get("qty_remaining") or 0) > 0
    ]
    order_id = agreements.call_off(env, agreement_id, lines)
    return {
        "ok": True,
        "message": "RFQ created from the agreement.",
        "order_id": order_id,
    }


@object_action("purchase.landed_cost", "action_post")
def post_landed_cost(env: Env, cost_id: int):
    return landed_costs.post_landed_cost(env, cost_id)


@object_action("purchase.analysis", "action_run")
def run_analysis(env: Env, analysis_id: int):
    return analysis.run(env, analysis_id)
