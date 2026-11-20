"""Closing, reporting, assets, loans and configuration records for A3."""

from __future__ import annotations

import datetime as dt

from ....orm import fields as f
from ....orm.model import BaseModel


class LockDate(BaseModel):
    _name = "accounting.lock_date"
    _table = "lock_date"
    _description = "Lock Date"
    _rec_name = "name"
    _order = "-id"

    xml_id = f.Char(index=True)
    name = f.Char(default="Lock Dates", required=True)
    company_id = f.Many2one("core.company", string="Company")
    date_sales = f.Date(string="Sales Lock Date")
    date_purchase = f.Date(string="Purchase Lock Date")
    date_hard = f.Date(string="Global Lock Date")
    reason = f.Char(string="Reason")


class TaxReturn(BaseModel):
    _name = "accounting.tax_return"
    _table = "tax_return"
    _description = "Tax Return"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True)
    date_from = f.Date(required=True)
    date_to = f.Date(required=True)
    state = f.Selection(
        [("draft", "Draft"), ("computed", "Computed"), ("posted", "Posted")],
        default="draft",
    )
    amount_total = f.Monetary(default=0, string="Tax Due")
    company_id = f.Many2one("core.company", string="Company")
    journal_id = f.Many2one("accounting.journal", string="Closing Journal")
    move_id = f.Many2one("accounting.move", string="Closing Entry")
    line_ids = f.One2many("accounting.tax_return_line", "return_id", string="Taxes")


class TaxReturnLine(BaseModel):
    _name = "accounting.tax_return_line"
    _table = "tax_return_line"
    _description = "Tax Return Line"
    _order = "id"

    return_id = f.Many2one(
        "accounting.tax_return", string="Tax Return", required=True, index=True
    )
    tax_id = f.Many2one("accounting.tax", string="Tax")
    label = f.Char(required=True)
    base_amount = f.Monetary(default=0, string="Base")
    tax_amount = f.Monetary(default=0, string="Tax")


class AssetModel(BaseModel):
    _name = "accounting.asset_model"
    _table = "asset_model"
    _description = "Asset Model"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    method = f.Selection(
        [("straight_line", "Straight Line"), ("declining", "Declining")],
        default="straight_line",
    )
    duration_months = f.Integer(default=60, string="Duration (months)")
    asset_account_id = f.Many2one("accounting.account", string="Asset Account")
    depreciation_account_id = f.Many2one(
        "accounting.account", string="Accumulated Depreciation"
    )
    expense_account_id = f.Many2one(
        "accounting.account", string="Depreciation Expense"
    )
    journal_id = f.Many2one("accounting.journal", string="Journal")
    active = f.Boolean(default=True)


class Asset(BaseModel):
    _name = "accounting.asset"
    _table = "asset"
    _description = "Asset"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True, index=True)
    model_id = f.Many2one("accounting.asset_model", string="Model")
    partner_id = f.Many2one("core.partner", string="Partner")
    original_value = f.Monetary(default=0, string="Original Value")
    date_start = f.Date(required=True, string="Start Date")
    state = f.Selection(
        [("draft", "Draft"), ("running", "Running"), ("closed", "Closed")],
        default="draft",
    )
    company_id = f.Many2one("core.company", string="Company")
    note = f.Text()
    line_ids = f.One2many("accounting.asset_line", "asset_id", string="Schedule")


class AssetLine(BaseModel):
    _name = "accounting.asset_line"
    _table = "asset_line"
    _description = "Depreciation Line"
    _order = "date, id"

    asset_id = f.Many2one(
        "accounting.asset", string="Asset", required=True, index=True
    )
    date = f.Date(required=True)
    amount = f.Monetary(default=0)
    move_id = f.Many2one("accounting.move", string="Entry")
    state = f.Selection([("draft", "Draft"), ("posted", "Posted")], default="draft")


class Loan(BaseModel):
    _name = "accounting.loan"
    _table = "loan"
    _description = "Loan"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True)
    partner_id = f.Many2one("core.partner", string="Lender")
    amount = f.Monetary(default=0, string="Principal")
    rate = f.Float(default=0, string="Annual Rate (%)")
    date_start = f.Date(required=True, string="Start Date")
    duration_months = f.Integer(default=12, string="Duration (months)")
    state = f.Selection(
        [("draft", "Draft"), ("running", "Running"), ("closed", "Closed")],
        default="draft",
    )
    loan_account_id = f.Many2one("accounting.account", string="Loan Account")
    interest_account_id = f.Many2one("accounting.account", string="Interest Expense")
    bank_account_id = f.Many2one("accounting.account", string="Bank Account")
    journal_id = f.Many2one("accounting.journal", string="Journal")
    company_id = f.Many2one("core.company", string="Company")
    line_ids = f.One2many("accounting.loan_line", "loan_id", string="Schedule")


class LoanLine(BaseModel):
    _name = "accounting.loan_line"
    _table = "loan_line"
    _description = "Loan Line"
    _order = "date, id"

    loan_id = f.Many2one("accounting.loan", string="Loan", required=True, index=True)
    date = f.Date(required=True)
    principal = f.Monetary(default=0)
    interest = f.Monetary(default=0)
    move_id = f.Many2one("accounting.move", string="Entry")
    state = f.Selection([("draft", "Draft"), ("posted", "Posted")], default="draft")


class Deferral(BaseModel):
    _name = "accounting.deferral"
    _table = "deferral"
    _description = "Deferred Revenue or Expense"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True)
    kind = f.Selection(
        [("revenue", "Deferred Revenue"), ("expense", "Deferred Expense")],
        default="revenue",
        required=True,
    )
    partner_id = f.Many2one("core.partner", string="Partner")
    amount = f.Monetary(default=0)
    date_start = f.Date(required=True, string="Start Date")
    periods = f.Integer(default=12)
    account_id = f.Many2one("accounting.account", string="Deferral Account")
    counterpart_account_id = f.Many2one(
        "accounting.account", string="Counterpart Account"
    )
    journal_id = f.Many2one("accounting.journal", string="Journal")
    state = f.Selection(
        [("draft", "Draft"), ("running", "Running"), ("closed", "Closed")],
        default="draft",
    )
    company_id = f.Many2one("core.company", string="Company")
    line_ids = f.One2many("accounting.deferral_line", "deferral_id", string="Schedule")


class DeferralLine(BaseModel):
    _name = "accounting.deferral_line"
    _table = "deferral_line"
    _description = "Deferral Line"
    _order = "date, id"

    deferral_id = f.Many2one(
        "accounting.deferral", string="Deferral", required=True, index=True
    )
    date = f.Date(required=True)
    amount = f.Monetary(default=0)
    move_id = f.Many2one("accounting.move", string="Entry")
    state = f.Selection([("draft", "Draft"), ("posted", "Posted")], default="draft")


class ReconciliationModel(BaseModel):
    _name = "accounting.reconciliation_model"
    _table = "reconciliation_model"
    _description = "Reconciliation Model"
    _rec_name = "name"
    _order = "sequence, name"

    xml_id = f.Char(index=True)

    name = f.Char(required=True)
    rule_type = f.Selection(
        [("label", "Label Contains"), ("amount", "Exact Amount")], default="label"
    )
    pattern = f.Char()
    sequence = f.Integer(default=10)
    journal_id = f.Many2one("accounting.journal", string="Journal")
    active = f.Boolean(default=True)


class BankStatement(BaseModel):
    _name = "accounting.bank_statement"
    _table = "bank_statement"
    _description = "Bank Statement"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True)
    journal_id = f.Many2one("accounting.journal", string="Journal", required=True)
    date = f.Date(required=True)
    state = f.Selection(
        [("draft", "Draft"), ("imported", "Imported"), ("closed", "Closed")],
        default="draft",
    )
    import_payload = f.Text(string="CSV to Import")
    company_id = f.Many2one("core.company", string="Company")
    line_ids = f.One2many(
        "accounting.bank_statement_line", "statement_id", string="Lines"
    )


class BankStatementLine(BaseModel):
    _name = "accounting.bank_statement_line"
    _table = "bank_statement_line"
    _description = "Bank Statement Line"
    _order = "date, id"

    statement_id = f.Many2one(
        "accounting.bank_statement", string="Statement", required=True, index=True
    )
    date = f.Date(required=True)
    label = f.Char(required=True)
    amount = f.Monetary(default=0)
    partner_id = f.Many2one("core.partner", string="Partner")
    state = f.Selection(
        [("pending", "Pending"), ("matched", "Matched"), ("ignored", "Ignored")],
        default="pending",
    )
    matched_move_id = f.Many2one("accounting.move", string="Matched Entry")
    payment_id = f.Many2one("accounting.payment", string="Payment")


class ReportDefinition(BaseModel):
    _name = "accounting.report"
    _table = "report"
    _description = "Accounting Report"
    _rec_name = "name"
    _order = "name"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    report_type = f.Selection(
        [
            ("balance_sheet", "Balance Sheet"),
            ("profit_and_loss", "Profit and Loss"),
            ("cash_flow", "Cash Flow Statement"),
            ("trial_balance", "Trial Balance"),
            ("general_ledger", "General Ledger"),
            ("partner_ledger", "Partner Ledger"),
            ("aged_receivable", "Aged Receivable"),
            ("aged_payable", "Aged Payable"),
            ("tax_report", "Tax Report"),
            ("ec_sales_list", "EC Sales List"),
            ("fiscal_report", "Fiscal Report"),
            ("invoice_analysis", "Invoice Analysis"),
            ("analytic_report", "Analytic Report"),
            ("executive_summary", "Executive Summary"),
            ("unrealized_currencies", "Unrealized Currencies"),
            ("billed_not_received", "Billed Not Received"),
            ("bill_to_receive", "Bill To Receive"),
            ("invoices_to_issue", "Invoices To Be Issued"),
            ("invoiced_not_delivered", "Invoiced Not Delivered"),
        ],
        required=True,
    )
    date_from = f.Date(required=True)
    date_to = f.Date(required=True)
    state = f.Selection(
        [("draft", "Draft"), ("computed", "Computed")], default="draft"
    )
    note = f.Char()
    company_id = f.Many2one("core.company", string="Company")
    line_ids = f.One2many("accounting.report_line", "report_id", string="Lines")


class ReportLine(BaseModel):
    _name = "accounting.report_line"
    _table = "report_line"
    _description = "Report Line"
    _order = "sequence, id"

    report_id = f.Many2one(
        "accounting.report", string="Report", required=True, index=True
    )
    sequence = f.Integer(default=10)
    label = f.Char(required=True)
    amount = f.Monetary(default=0)
    level = f.Integer(default=1, string="Indent")
    style = f.Selection(
        [("line", "Line"), ("section", "Section"), ("total", "Total")],
        default="line",
    )


class AnalyticPlan(BaseModel):
    _name = "accounting.analytic_plan"
    _table = "analytic_plan"
    _description = "Analytic Plan"
    _rec_name = "name"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    code = f.Char()
    active = f.Boolean(default=True)


class AnalyticAccount(BaseModel):
    _name = "accounting.analytic_account"
    _table = "analytic_account"
    _description = "Analytic Account"
    _rec_name = "name"
    _order = "code, name"

    xml_id = f.Char(index=True)

    name = f.Char(required=True)
    code = f.Char()
    plan_id = f.Many2one("accounting.analytic_plan", string="Plan")
    partner_id = f.Many2one("core.partner", string="Partner")
    balance = f.Monetary(default=0, string="Balance")
    active = f.Boolean(default=True)


class Budget(BaseModel):
    _name = "accounting.budget"
    _table = "budget"
    _description = "Financial Budget"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True)
    date_from = f.Date(required=True)
    date_to = f.Date(required=True)
    company_id = f.Many2one("core.company", string="Company")
    line_ids = f.One2many("accounting.budget_line", "budget_id", string="Lines")


class BudgetLine(BaseModel):
    _name = "accounting.budget_line"
    _table = "budget_line"
    _description = "Budget Line"
    _order = "id"

    budget_id = f.Many2one(
        "accounting.budget", string="Budget", required=True, index=True
    )
    account_id = f.Many2one("accounting.account", string="Account")
    name = f.Char(required=True)
    planned_amount = f.Monetary(default=0)
    actual_amount = f.Monetary(default=0)
    variance = f.Monetary(default=0)


class FollowupLevel(BaseModel):
    _name = "accounting.followup_level"
    _table = "followup_level"
    _description = "Follow-up Level"
    _rec_name = "name"
    _order = "delay_days"

    xml_id = f.Char(index=True)

    name = f.Char(required=True)
    delay_days = f.Integer(default=0, string="Days Overdue")
    active = f.Boolean(default=True)


class PaymentProvider(BaseModel):
    _name = "accounting.payment_provider"
    _table = "payment_provider"
    _description = "Payment Provider"
    _rec_name = "name"
    _order = "name"

    xml_id = f.Char(index=True)

    name = f.Char(required=True)
    code = f.Char(index=True)
    state = f.Selection(
        [("disabled", "Disabled"), ("test", "Test"), ("enabled", "Enabled")],
        default="test",
    )
    journal_id = f.Many2one("accounting.journal", string="Journal")
    active = f.Boolean(default=True)


class PaymentMethod(BaseModel):
    _name = "accounting.payment_method"
    _table = "payment_method"
    _description = "Payment Method"
    _rec_name = "name"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    code = f.Char(index=True)
    provider_id = f.Many2one("accounting.payment_provider", string="Provider")
    active = f.Boolean(default=True)


class PaymentToken(BaseModel):
    _name = "accounting.payment_token"
    _table = "payment_token"
    _description = "Payment Token"
    _rec_name = "name"

    name = f.Char(required=True)
    partner_id = f.Many2one("core.partner", string="Partner")
    provider_id = f.Many2one("accounting.payment_provider", string="Provider")
    token = f.Char()
    active = f.Boolean(default=True)


class PaymentTransaction(BaseModel):
    _name = "accounting.payment_transaction"
    _table = "payment_transaction"
    _description = "Payment Transaction"
    _rec_name = "name"
    _order = "-id"

    xml_id = f.Char(index=True)

    name = f.Char(required=True)
    provider_id = f.Many2one("accounting.payment_provider", string="Provider")
    partner_id = f.Many2one("core.partner", string="Partner")
    amount = f.Monetary(default=0)
    state = f.Selection(
        [("draft", "Draft"), ("pending", "Pending"), ("done", "Done"), ("error", "Error")],
        default="draft",
    )
    reference = f.Char()


class ConfigItem(BaseModel):
    """Small configuration tables that share one shape."""

    _name = "accounting.config_item"
    _table = "config_item"
    _description = "Accounting Configuration"
    _rec_name = "name"
    _order = "kind, name"

    xml_id = f.Char(index=True)

    kind = f.Char(required=True, index=True)
    name = f.Char(required=True)
    code = f.Char()
    description = f.Text()
    amount = f.Monetary(default=0)
    active = f.Boolean(default=True)


class EdiDocument(BaseModel):
    _name = "accounting.edi_document"
    _table = "edi_document"
    _description = "E-Invoicing Document"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True)
    move_id = f.Many2one("accounting.move", string="Invoice", required=True)
    status = f.Selection(
        [("draft", "Draft"), ("sent", "Sent"), ("accepted", "Accepted"), ("error", "Error")],
        default="draft",
    )
    payload = f.Text()
    reference = f.Char(string="eTIMS Reference")
    generated_at = f.Datetime()
    error = f.Char()


def month_add(date: dt.date, months: int) -> dt.date:
    """Add calendar months, clamping the day to the target month's length."""
    year = date.year + (date.month - 1 + months) // 12
    month = (date.month - 1 + months) % 12 + 1
    day = min(date.day, 28)
    return dt.date(year, month, day)

