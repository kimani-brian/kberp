"""Sales settings, owned by the sales module."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class Settings(BaseModel):
    _name = "sales.settings"
    _table = "settings"
    _description = "Sales Settings"
    _rec_name = "name"
    _unique_together = (("company_id",),)

    xml_id = f.Char(index=True)
    name = f.Char(default="Sales Settings", required=True)
    company_id = f.Many2one("core.company", string="Company")
    validity_days = f.Integer(default=30, string="Quotation Validity (days)")
    invoice_policy = f.Selection(
        [("ordered", "Ordered quantities"), ("delivered", "Delivered quantities")],
        default="ordered",
        string="Invoicing Policy",
    )
    allow_discount = f.Boolean(default=True, string="Allow Discounts")
