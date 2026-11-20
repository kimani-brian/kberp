"""Platform: transactional outbox and scheduled jobs."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class OutboxEvent(BaseModel):
    _name = "platform.outbox_event"
    _schema = "platform"
    _table = "outbox_event"
    _description = "Outbox Event"
    _order = "id"

    event_type = f.Char(required=True, index=True)
    payload = f.Text(default="{}")
    state = f.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("processed", "Processed"),
            ("failed", "Failed"),
        ],
        default="pending",
        index=True,
    )
    attempts = f.Integer(default=0)
    max_attempts = f.Integer(default=5)
    error = f.Text()
    processed_at = f.Datetime()


class BusMessage(BaseModel):
    _name = "platform.bus_message"
    _schema = "platform"
    _table = "bus_message"
    _description = "Bus Message"
    _order = "id"

    channel = f.Char(required=True, index=True)
    event = f.Char(required=True, index=True)
    payload = f.Text(default="{}")


class IrCron(BaseModel):
    _name = "core.ir_cron"
    _table = "ir_cron"
    _description = "Scheduled Action"
    _rec_name = "name"
    _order = "next_call, id"

    name = f.Char(required=True)
    code = f.Char(required=True, help="Dotted path to a callable: package.module.function")
    interval_minutes = f.Integer(default=60)
    active = f.Boolean(default=True)
    last_call = f.Datetime()
    next_call = f.Datetime()
