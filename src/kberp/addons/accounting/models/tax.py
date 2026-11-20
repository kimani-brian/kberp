"""Taxes and their repartition rules."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class TaxGroup(BaseModel):
    _name = "accounting.tax_group"
    _table = "tax_group"
    _description = "Tax Group"
    _rec_name = "name"
    _order = "sequence, id"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    sequence = f.Integer(default=10)


class TaxRepartition(BaseModel):
    _name = "accounting.tax_repartition"
    _table = "tax_repartition"
    _description = "Tax Repartition"
    _order = "id"

    tax_id = f.Many2one("accounting.tax", string="Tax", required=True, index=True)
    account_id = f.Many2one("accounting.account", string="Account")
    factor = f.Float(default=1, string="Factor")
    label = f.Char()


class Tax(BaseModel):
    _name = "accounting.tax"
    _table = "tax"
    _description = "Tax"
    _rec_name = "name"
    _order = "sequence, id"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    amount = f.Float(default=0, string="Amount")
    amount_type = f.Selection(
        [("percent", "Percentage"), ("fixed", "Fixed")], default="percent", string="Type"
    )
    price_include = f.Boolean(default=False, string="Included in Price")
    rounding = f.Selection(
        [("line", "Per line"), ("total", "Per total")], default="line", string="Rounding"
    )
    group_id = f.Many2one("accounting.tax_group", string="Tax Group")
    sequence = f.Integer(default=10)
    active = f.Boolean(default=True)
    company_id = f.Many2one("core.company", string="Company")
    repartition_ids = f.One2many(
        "accounting.tax_repartition", "tax_id", string="Repartition"
    )
