"""Kernel metadata: modules, menus, actions, views, access control."""

from __future__ import annotations

from psycopg import sql

from ....orm import fields as f
from ....orm.model import BaseModel, ValidationError


class IrModule(BaseModel):
    _name = "core.ir_module"
    _table = "ir_module"
    _description = "Module"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True, index=True)
    label = f.Char()
    version = f.Char()
    state = f.Selection(
        [("installed", "Installed"), ("to upgrade", "To Upgrade"), ("uninstalled", "Uninstalled")],
        default="installed",
    )


class IrUiMenu(BaseModel):
    _unique_fields = ("xml_id",)
    _name = "core.ir_ui_menu"
    _table = "ir_ui_menu"
    _description = "Menu Item"
    _order = "sequence, id"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)
    parent_id = f.Many2one("core.ir_ui_menu", string="Parent Menu")
    sequence = f.Integer(default=10)
    is_app = f.Boolean(default=False)
    web_icon = f.Char()
    groups = f.Char(string="Visible to Groups")
    action_type = f.Selection([("window", "Window"), ("client", "Client")])
    action_id = f.Integer()
    action_xmlid = f.Char()


class IrActWindow(BaseModel):
    _unique_fields = ("xml_id",)
    _name = "core.ir_act_window"
    _table = "ir_act_window"
    _description = "Window Action"
    _rec_name = "name"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)
    res_model = f.Char(required=True)
    view_mode = f.Char(default="list,form")
    domain = f.Text(default="[]")
    context = f.Text(default="{}")
    path = f.Char()


class IrActClient(BaseModel):
    _unique_fields = ("xml_id",)
    _name = "core.ir_act_client"
    _table = "ir_act_client"
    _description = "Client Action"
    _rec_name = "name"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)
    tag = f.Char(required=True)
    params = f.Text(default="{}")


class IrUiView(BaseModel):
    _unique_fields = ("xml_id",)
    _name = "core.ir_ui_view"
    _table = "ir_ui_view"
    _description = "View"
    _order = "priority, id"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)
    model = f.Char(required=True, index=True)
    type = f.Selection(
        [("list", "List"), ("form", "Form"), ("kanban", "Kanban"), ("search", "Search")],
        required=True,
    )
    arch = f.Text(required=True)
    priority = f.Integer(default=16)


class IrRule(BaseModel):
    """A row filter applied on top of model access rights.

    `group_xmlid` empty means the rule is global. A domain may use the literal
    `"$company"` where the signed-in user's company id belongs; `Env` replaces
    it before the domain is compiled, which keeps one rule correct for every
    company without writing a rule per user.
    """

    _unique_fields = ("xml_id",)
    _name = "core.ir_rule"
    _table = "ir_rule"
    _description = "Record Rule"
    _rec_name = "name"
    _order = "model, id"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)
    model = f.Char(required=True, index=True)
    domain = f.Text(default="[]")
    group_xmlid = f.Char(index=True)
    is_global = f.Boolean(string="Global", default=False)
    perm_read = f.Boolean(default=True)
    perm_write = f.Boolean(default=True)
    perm_create = f.Boolean(default=True)
    perm_unlink = f.Boolean(default=True)


class IrModelAccess(BaseModel):
    _unique_fields = ("xml_id",)
    _name = "core.ir_model_access"
    _table = "ir_model_access"
    _description = "Access Control"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)
    model = f.Char(required=True, index=True)
    group_xmlid = f.Char(required=True, index=True)
    perm_read = f.Boolean(default=True)
    perm_write = f.Boolean(default=False)
    perm_create = f.Boolean(default=False)
    perm_unlink = f.Boolean(default=False)


class ResGroups(BaseModel):
    _unique_fields = ("xml_id",)
    _name = "core.res_groups"
    _table = "res_groups"
    _description = "Security Group"
    _rec_name = "name"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)


class IrSequence(BaseModel):
    """A database-backed, gap-free counter for document numbers."""

    _unique_fields = ("xml_id",)
    _name = "core.ir_sequence"
    _table = "ir_sequence"
    _description = "Sequence"
    _rec_name = "name"

    xml_id = f.Char(required=True, index=True)
    name = f.Char(required=True)
    prefix = f.Char(default="")
    padding = f.Integer(default=5)
    number_next = f.Integer(default=1)

    def next_code(self, code: str) -> str:
        """Return the next number in the sequence, without ever reusing one.

        The counter is updated with a single statement, so two confirmations in
        different transactions still get different numbers.
        """
        ids = self.search([("xml_id", "=", code)], limit=1)
        if not ids:
            raise ValidationError(f"unknown sequence {code!r}")
        row = self.env.db.fetch_one(
            sql.SQL(
                "UPDATE {}.{} SET number_next = number_next + 1 "
                "WHERE id = %s RETURNING number_next"
            ).format(sql.Identifier(self._schema or "core"), sql.Identifier(self._table)),
            (ids[0],),
        )
        number = int(row[0]) if row else 0
        sequence = self.read([ids[0]])[0]
        return f"{sequence['prefix']}{number:0{sequence['padding']}d}"
