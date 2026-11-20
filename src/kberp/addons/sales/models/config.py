"""Small configuration records introduced with S2."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class Tag(BaseModel):
    _name = "sales.tag"
    _table = "tag"
    _description = "Sales Tag"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    color = f.Integer(default=0)


class HeaderFooter(BaseModel):
    _name = "sales.header_footer"
    _table = "header_footer"
    _description = "Quotation Header / Footer"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    header = f.Text()
    footer = f.Text()
    active = f.Boolean(default=True)
