"""Payments, payment terms, fiscal positions and their allocations."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class PaymentTerm(BaseModel):
    _name = "accounting.payment_term"
    _table = "payment_term"
    _description = "Payment Terms"
    _rec_name = "name"
    _order = "days, name"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    days = f.Integer(default=0, string="Days from Invoice")
    active = f.Boolean(default=True)


class FiscalPosition(BaseModel):
    _name = "accounting.fiscal_position"
    _table = "fiscal_position"
    _description = "Fiscal Position"
    _rec_name = "name"
    _order = "name"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    country_id = f.Many2one("core.country", string="Country")
    source_tax_id = f.Many2one("accounting.tax", string="Source Tax")
    dest_tax_id = f.Many2one("accounting.tax", string="Replacement Tax")
    source_account_id = f.Many2one("accounting.account", string="Source Account")
    dest_account_id = f.Many2one("accounting.account", string="Replacement Account")
    active = f.Boolean(default=True)


class Payment(BaseModel):
    _name = "accounting.payment"
    _table = "payment"
    _description = "Payment"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True, index=True, string="Number")
    payment_type = f.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")],
        default="inbound",
        required=True,
    )
    partner_id = f.Many2one("core.partner", string="Partner", required=True, index=True)
    journal_id = f.Many2one("accounting.journal", string="Journal", required=True)
    amount = f.Monetary(default=0, string="Amount")
    amount_company = f.Monetary(default=0, string="Company Amount")
    currency_id = f.Many2one("core.currency", string="Currency")
    currency_rate = f.Float(default=1, string="Rate")
    date = f.Date(required=True)
    method = f.Char(string="Method")
    memo = f.Char()
    state = f.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancel", "Cancelled")],
        default="draft",
        required=True,
    )
    company_id = f.Many2one("core.company", string="Company")
    payment_line_ids = f.One2many(
        "accounting.payment_line", "payment_id", string="Allocations"
    )


class PaymentLine(BaseModel):
    _name = "accounting.payment_line"
    _table = "payment_line"
    _description = "Payment Allocation"
    _order = "id"

    payment_id = f.Many2one("accounting.payment", string="Payment", required=True, index=True)
    move_id = f.Many2one("accounting.move", string="Invoice", required=True, index=True)
    amount = f.Monetary(default=0, string="Allocated")
