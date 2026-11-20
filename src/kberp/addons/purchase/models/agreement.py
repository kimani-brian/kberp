"""Blanket agreements, approvals and landed costs."""

from __future__ import annotations

from typing import Any

from ....orm import fields as f
from ....orm.model import BaseModel, ValidationError

AGREEMENT_STATES = [
    ("draft", "Draft"),
    ("running", "Running"),
    ("closed", "Closed"),
    ("cancel", "Cancelled"),
]

APPROVAL_STATES = [
    ("not_required", "Not Required"),
    ("waiting", "Waiting Approval"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]

SPLIT_METHODS = [
    ("equal", "Equal"),
    ("by_quantity", "By Quantity"),
    ("by_value", "By Value"),
]


class Agreement(BaseModel):
    _name = "purchase.agreement"
    _table = "agreement"
    _description = "Purchase Agreement"
    _rec_name = "name"
    _order = "-id"

    xml_id = f.Char(index=True)
    name = f.Char(required=True, index=True)
    partner_id = f.Many2one("core.partner", string="Vendor", required=True, index=True)
    agreement_type = f.Selection(
        [("blanket", "Blanket Order"), ("contract", "Purchase Contract")],
        default="blanket",
        string="Type",
    )
    date_start = f.Date(required=True, string="Start Date")
    date_end = f.Date(required=True, string="End Date")
    state = f.Selection(AGREEMENT_STATES, default="draft", required=True)
    currency_id = f.Many2one("core.currency", string="Currency")
    company_id = f.Many2one("core.company", string="Company")
    note = f.Text()
    line_ids = f.One2many("purchase.agreement_line", "agreement_id", string="Lines")

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        if not values.get("name"):
            values["name"] = (
                f"AGR/{self.env['core.ir_sequence'].next_code('purchase.seq_agreement')}"
            )
        record_id = super().create(values)
        self._recompute([record_id])
        return record_id

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        updated = super().write(ids, values)
        self._recompute([int(record_id) for record_id in ids])
        return updated

    def _recompute(self, ids: list[int]) -> None:
        if not ids or self.env.context.get("skip_totals"):
            return
        from ..services.agreements import recompute_agreement

        recompute_agreement(self.env, ids)


class AgreementLine(BaseModel):
    _name = "purchase.agreement_line"
    _table = "agreement_line"
    _description = "Agreement Line"
    _order = "sequence, id"

    agreement_id = f.Many2one(
        "purchase.agreement", string="Agreement", required=True, index=True
    )
    sequence = f.Integer(default=10)
    product_id = f.Many2one("core.product_template", string="Product")
    name = f.Char(required=True)
    qty = f.Float(default=1, string="Agreed Quantity")
    qty_called = f.Float(default=0, string="Called Off")
    qty_remaining = f.Float(default=0, string="Remaining")
    uom_id = f.Many2one("core.uom", string="Unit of Measure")
    price_unit = f.Monetary(default=0, string="Unit Price")
    tax_ids = f.Many2many("accounting.tax", string="Taxes")


class LandedCost(BaseModel):
    _name = "purchase.landed_cost"
    _table = "landed_cost"
    _description = "Landed Cost"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True, index=True)
    picking_id = f.Many2one("inventory.picking", string="Receipt", required=True)
    vendor_id = f.Many2one("core.partner", string="Vendor")
    date = f.Date(required=True)
    state = f.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancel", "Cancelled")],
        default="draft",
        required=True,
    )
    split_method = f.Selection(SPLIT_METHODS, default="by_value", string="Split Method")
    amount_total = f.Monetary(default=0, string="Total")
    account_id = f.Many2one("accounting.account", string="Expense Account")
    journal_id = f.Many2one("accounting.journal", string="Journal")
    company_id = f.Many2one("core.company", string="Company")
    currency_id = f.Many2one("core.currency", string="Currency")
    valuation_move_id = f.Many2one("accounting.move", string="Accounting Entry")
    line_ids = f.One2many("purchase.landed_cost_line", "cost_id", string="Cost Lines")

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        if not values.get("name"):
            values["name"] = (
                f"LC/{self.env['core.ir_sequence'].next_code('purchase.seq_landed_cost')}"
            )
        record_id = super().create(values)
        self._recompute([record_id])
        return record_id

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        updated = super().write(ids, values)
        self._recompute([int(record_id) for record_id in ids])
        return updated

    def _recompute(self, ids: list[int]) -> None:
        if not ids or self.env.context.get("skip_totals"):
            return
        for cost in self.read(ids):
            total = sum(float(line["amount"] or 0) for line in cost.get("line_ids", []))
            self.env.with_context(skip_totals=True)["purchase.landed_cost"].write(
                [cost["id"]], {"amount_total": total}
            )


class LandedCostLine(BaseModel):
    _name = "purchase.landed_cost_line"
    _table = "landed_cost_line"
    _description = "Landed Cost Line"
    _order = "id"

    cost_id = f.Many2one(
        "purchase.landed_cost", string="Landed Cost", required=True, index=True
    )
    name = f.Char(required=True)
    product_id = f.Many2one("core.product_template", string="Product")
    amount = f.Monetary(default=0)
    account_id = f.Many2one("accounting.account", string="Account")
    split_method = f.Selection(SPLIT_METHODS, default="by_value", string="Split Method")


class Analysis(BaseModel):
    """A saved purchase analysis, regenerated on demand."""

    _name = "purchase.analysis"
    _table = "analysis"
    _description = "Purchase Analysis"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True)
    date_from = f.Date(required=True)
    date_to = f.Date(required=True)
    group_by = f.Selection(
        [("vendor", "Vendor"), ("product", "Product"), ("category", "Category")],
        default="vendor",
    )
    state = f.Selection(
        [("draft", "Draft"), ("computed", "Computed")], default="draft"
    )
    company_id = f.Many2one("core.company", string="Company")
    line_ids = f.One2many("purchase.analysis_line", "analysis_id", string="Rows")


class AnalysisLine(BaseModel):
    _name = "purchase.analysis_line"
    _table = "analysis_line"
    _description = "Purchase Analysis Row"
    _order = "sequence, id"

    analysis_id = f.Many2one(
        "purchase.analysis", string="Analysis", required=True, index=True
    )
    sequence = f.Integer(default=10)
    label = f.Char(required=True)
    qty = f.Float(default=0)
    amount = f.Monetary(default=0, string="Amount")


def validate_dates(date_start, date_end) -> None:
    if date_start and date_end and date_start > date_end:
        raise ValidationError("the agreement end date cannot be before its start date")
