"""Chatter core: messages, followers and activities on any business record.

P0 shipped the message stream. C1 adds the two pieces a directory needs:
who follows a contact, and what has to happen next. Activities are deliberately
plain rows (type, summary, deadline, owner) so a later calendar or mail phase
can read them without changing the shape.
"""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class Message(BaseModel):
    _name = "chatter.message"
    _schema = "chatter"
    _table = "message"
    _description = "Message"
    _order = "-id"

    model = f.Char(required=True, index=True)
    res_id = f.Integer(required=True, index=True)
    body = f.Text(required=True)
    author_id = f.Many2one("core.user", string="Author")
    message_type = f.Selection(
        [("note", "Note"), ("comment", "Comment")], default="note", index=True
    )


class Follower(BaseModel):
    _name = "chatter.follower"
    _schema = "chatter"
    _table = "follower"
    _description = "Follower"
    _order = "-id"
    _unique_together = (("model", "res_id", "partner_id"),)

    model = f.Char(required=True, index=True)
    res_id = f.Integer(required=True, index=True)
    partner_id = f.Many2one("core.partner", string="Contact", required=True, index=True)
    active = f.Boolean(default=True)


class ActivityType(BaseModel):
    _name = "chatter.activity_type"
    _schema = "chatter"
    _table = "activity_type"
    _description = "Activity Type"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    icon = f.Char(default="")
    days = f.Integer(string="Default Days", default=0)
    active = f.Boolean(default=True)


class Activity(BaseModel):
    _name = "chatter.activity"
    _schema = "chatter"
    _table = "activity"
    _description = "Activity"
    _order = "date_deadline, id"

    model = f.Char(required=True, index=True)
    res_id = f.Integer(required=True, index=True)
    activity_type_id = f.Many2one(
        "chatter.activity_type", string="Activity Type", required=True
    )
    summary = f.Char(string="Summary")
    date_deadline = f.Date(string="Due Date")
    user_id = f.Many2one("core.user", string="Assigned To")
    note = f.Text(string="Note")
    state = f.Selection(
        [("planned", "Planned"), ("done", "Done"), ("cancelled", "Cancelled")],
        default="planned",
        index=True,
    )
    active = f.Boolean(default=True)

    def complete(self, activity_id: int, *, user_id: int | None = None) -> None:
        """Mark one activity done and leave a chatter note behind."""
        rows = self.read([activity_id])
        if not rows:
            return
        activity = rows[0]
        self.write([activity_id], {"state": "done", "active": False})
        env = self.env
        env["chatter.message"].create(
            {
                "model": activity["model"],
                "res_id": activity["res_id"],
                "body": f"Activity done: {activity.get('summary') or 'Activity'}",
                "author_id": user_id,
                "message_type": "note",
            }
        )
