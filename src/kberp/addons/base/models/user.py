"""Users and sessions."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class User(BaseModel):
    _name = "core.user"
    _table = "res_users"
    _description = "User"
    _rec_name = "name"
    _order = "name"
    _unique_fields = ("login",)

    name = f.Char(required=True)
    login = f.Char(required=True, index=True)
    password_hash = f.Char(string="Password Hash")
    is_admin = f.Boolean(string="Administrator", default=False)
    active = f.Boolean(default=True)
    group_xmlids = f.StringList(string="Groups")
    company_id = f.Many2one("core.company", string="Company")
    partner_id = f.Many2one("core.partner", string="Contact")


class Session(BaseModel):
    _name = "platform.session"
    _schema = "platform"
    _table = "session"
    _description = "Session"
    _order = "id"
    _unique_fields = ("token",)

    token = f.Char(required=True, index=True)
    user_id = f.Many2one("core.user", string="User", required=True)
    csrf = f.Char(required=True)
    expires_at = f.Datetime(required=True)
    flash = f.Text(default="[]")
