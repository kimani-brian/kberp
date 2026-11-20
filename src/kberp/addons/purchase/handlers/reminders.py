"""Scheduled receipt reminders and vendor warnings."""

from __future__ import annotations

import datetime as dt

from ....env import Env


def send_receipt_reminders(env: Env) -> int:
    """Note every confirmed order whose receipt is due or late.

    Idempotent within a day: a note is only written once per order per day.
    """
    settings_ids = env["purchase.settings"].search([], limit=1)
    settings = (
        env["purchase.settings"].read([settings_ids[0]])[0] if settings_ids else {}
    )
    days = int(settings.get("receipt_reminder_days") or 3)
    cutoff = dt.date.today() + dt.timedelta(days=days)
    order_ids = env["purchase.order"].search(
        [
            ("state", "=", "purchase"),
            ("receipt_status", "!=", "full"),
            ("expected_date", "<=", cutoff),
        ]
    )
    sent = 0
    for order in env["purchase.order"].read(order_ids):
        body = (
            f"Receipt reminder: {order['name']} is due on "
            f"{order.get('expected_date') or 'an unset date'}."
        )
        existing = env["chatter.message"].search(
            [
                ("model", "=", "purchase.order"),
                ("res_id", "=", order["id"]),
                ("body", "=", body),
            ],
            limit=1,
        )
        if existing:
            continue
        env["chatter.message"].create(
            {
                "model": "purchase.order",
                "res_id": order["id"],
                "body": body,
                "author_id": env.uid,
                "message_type": "note",
            }
        )
        sent += 1
    return sent
