"""Chart of accounts, journals, moves and the posting audit trail."""

from __future__ import annotations

from typing import Any

from ....orm import fields as f
from ....orm.model import BaseModel, ValidationError

ACCOUNT_TYPES = [
    ("asset", "Asset"),
    ("bank", "Bank"),
    ("receivable", "Receivable"),
    ("liability", "Liability"),
    ("payable", "Payable"),
    ("equity", "Equity"),
    ("income", "Income"),
    ("expense", "Expense"),
]

JOURNAL_TYPES = [
    ("general", "General"),
    ("sale", "Sale"),
    ("purchase", "Purchase"),
    ("bank", "Bank"),
    ("cash", "Cash"),
]

MOVE_TYPES = [
    ("entry", "Journal Entry"),
    ("out_invoice", "Customer Invoice"),
    ("in_invoice", "Vendor Bill"),
    ("out_refund", "Customer Credit Note"),
    ("in_refund", "Vendor Refund"),
]


class Account(BaseModel):
    _name = "accounting.account"
    _table = "account"
    _description = "Account"
    _rec_name = "name"
    _order = "code, id"
    _unique_together = (("code", "company_id"),)

    xml_id = f.Char(index=True)
    code = f.Char(required=True, index=True)
    name = f.Char(required=True)
    type = f.Selection(ACCOUNT_TYPES, required=True, default="asset")
    parent_id = f.Many2one("accounting.account", string="Parent Account")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)


class Journal(BaseModel):
    _name = "accounting.journal"
    _table = "journal"
    _description = "Journal"
    _rec_name = "name"
    _order = "code, id"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    code = f.Char(required=True, index=True)
    type = f.Selection(JOURNAL_TYPES, required=True, default="general")
    sequence_id = f.Many2one("core.ir_sequence", string="Number Sequence")
    default_account_id = f.Many2one("accounting.account", string="Default Account")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)


class FiscalYear(BaseModel):
    _name = "accounting.fiscal_year"
    _table = "fiscal_year"
    _description = "Fiscal Year"
    _rec_name = "name"
    _order = "date_start"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    date_start = f.Date(required=True)
    date_end = f.Date(required=True)
    company_id = f.Many2one("core.company", string="Company")


class Settings(BaseModel):
    _name = "accounting.settings"
    _table = "settings"
    _description = "Accounting Settings"
    _rec_name = "name"
    _unique_together = (("company_id",),)

    xml_id = f.Char(index=True)
    name = f.Char(default="Accounting Settings", required=True)
    company_id = f.Many2one("core.company", string="Company")
    receivable_account_id = f.Many2one("accounting.account", string="Receivable Account")
    payable_account_id = f.Many2one("accounting.account", string="Payable Account")
    income_account_id = f.Many2one("accounting.account", string="Income Account")
    expense_account_id = f.Many2one("accounting.account", string="Expense Account")
    tax_account_id = f.Many2one("accounting.account", string="Tax Account")
    bank_account_id = f.Many2one("accounting.account", string="Bank Account")
    exchange_account_id = f.Many2one("accounting.account", string="Exchange Difference Account")


class Move(BaseModel):
    _name = "accounting.move"
    _table = "move"
    _description = "Journal Entry"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(string="Number", index=True)
    move_type = f.Selection(MOVE_TYPES, default="entry", required=True)
    partner_id = f.Many2one("core.partner", string="Partner", index=True)
    journal_id = f.Many2one("accounting.journal", string="Journal", required=True)
    date = f.Date(required=True)
    due_date = f.Date(string="Due Date")
    state = f.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancel", "Cancelled")],
        default="draft",
        required=True,
    )
    amount_untaxed = f.Monetary(default=0, string="Untaxed")
    amount_tax = f.Monetary(default=0, string="Taxes")
    amount_total = f.Monetary(default=0, string="Total")
    amount_residual = f.Monetary(default=0, string="Residual")
    payment_state = f.Selection(
        [
            ("not paid", "Not Paid"),
            ("partial", "Partial"),
            ("paid", "Paid"),
            ("reversed", "Reversed"),
        ],
        default="not paid",
    )
    payment_term_id = f.Many2one("accounting.payment_term", string="Payment Terms")
    fiscal_position_id = f.Many2one("accounting.fiscal_position", string="Fiscal Position")
    currency_rate = f.Float(default=1, string="Rate")
    amount_debit = f.Monetary(default=0, string="Debit")
    amount_credit = f.Monetary(default=0, string="Credit")
    company_id = f.Many2one("core.company", string="Company")
    currency_id = f.Many2one("core.currency", string="Currency")
    origin = f.Char(string="Source Document", index=True)
    secured = f.Boolean(default=False, string="Secured")
    note = f.Text()
    line_ids = f.One2many("accounting.move_line", "move_id", string="Lines")

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        if values.get("move_type") in ("out_invoice", "in_invoice", "out_refund", "in_refund"):
            settings_ids = self.env["accounting.settings"].search([], limit=1)
            settings = (
                self.env["accounting.settings"].read([settings_ids[0]])[0]
                if settings_ids
                else {}
            )
            field = (
                "income_account_id"
                if values.get("move_type") in ("out_invoice", "out_refund")
                else "expense_account_id"
            )
            account = settings.get(field) or {}
            default_account = account.get("id") if isinstance(account, dict) else account
            lines = []
            for line in values.get("line_ids") or []:
                line = dict(line)
                if line.get("product_id") and not line.get("kind"):
                    line["kind"] = "product"
                if line.get("kind") == "product" and not line.get("account_id"):
                    line["account_id"] = default_account
                lines.append(line)
            values["line_ids"] = lines
        record_id = super().create(values)
        if not self.env.context.get("skip_totals"):
            self._recompute([record_id])
        return record_id

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        ids = [int(record_id) for record_id in ids]
        if not self.env.context.get("allow_posting"):
            self._check_mutable(ids, "edited")
            from ..services.closing import check_locked

            for row in self.read(ids):
                check_locked(self.env, row)
        updated = super().write(ids, values)
        if not self.env.context.get("skip_totals"):
            self._recompute(ids)
        return updated

    def _recompute(self, ids: list[int]) -> None:
        from ..services.posting import recompute_move

        recompute_move(self.env, ids)

    def unlink(self, ids: Any) -> int:
        ids = [int(record_id) for record_id in ids]
        if not self.env.context.get("allow_posting"):
            self._check_mutable(ids, "deleted")
        return super().unlink(ids)

    def _check_mutable(self, ids: list[int], action: str) -> None:
        rows = self.read(ids)
        posted = [
            row["name"] or f"#{row['id']}"
            for row in rows
            if row["state"] == "posted" or row.get("secured")
        ]
        if posted:
            raise ValidationError(
                f"posted or secured entries cannot be {action}: {', '.join(posted)}. "
                "Reverse them instead."
            )


class MoveLine(BaseModel):
    _name = "accounting.move_line"
    _table = "move_line"
    _description = "Journal Item"
    _order = "id"

    move_id = f.Many2one("accounting.move", string="Entry", required=True, index=True)
    account_id = f.Many2one("accounting.account", string="Account", required=True)
    partner_id = f.Many2one("core.partner", string="Partner")
    name = f.Char(string="Label")
    debit = f.Monetary(default=0)
    credit = f.Monetary(default=0)
    product_id = f.Many2one("core.product_template", string="Product")
    analytic_account_id = f.Many2one(
        "accounting.analytic_account", string="Analytic Account"
    )
    tax_id = f.Many2one("accounting.tax", string="Tax")
    qty = f.Float(default=1, string="Quantity")
    price_unit = f.Monetary(default=0, string="Unit Price")
    tax_ids = f.Many2many("accounting.tax", string="Taxes")
    subtotal = f.Monetary(default=0, string="Subtotal")
    kind = f.Selection(
        [
            ("manual", "Manual"),
            ("product", "Product"),
            ("tax", "Tax"),
            ("receivable", "Receivable"),
            ("payable", "Payable"),
        ],
        default="manual",
    )
    date = f.Date()

    def create(self, values: dict[str, Any]) -> int:
        self._check_parent(values.get("move_id"))
        return super().create(values)

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        if not self.env.context.get("allow_posting"):
            rows = self.read(ids)
            move_ids = {row["move_id"]["id"] for row in rows if row.get("move_id")}
            self._check_many(move_ids)
        return super().write(ids, values)

    def unlink(self, ids: Any) -> int:
        if not self.env.context.get("allow_posting"):
            rows = self.read(ids)
            move_ids = {row["move_id"]["id"] for row in rows if row.get("move_id")}
            self._check_many(move_ids)
        return super().unlink(ids)

    def _check_parent(self, move_id: Any) -> None:
        if self.env.context.get("allow_posting") or not move_id:
            return
        self._check_many({int(move_id)})

    def _check_many(self, move_ids: set[int]) -> None:
        if not move_ids:
            return
        moves = self.env["accounting.move"].read(list(move_ids))
        posted = [
            row["name"] or f"#{row['id']}"
            for row in moves
            if row["state"] == "posted" or row.get("secured")
        ]
        if posted:
            raise ValidationError(
                
                f"lines of posted entries cannot be changed (secured entries are immutable too): {', '.join(posted)}. "
                "Reverse the entry instead."
            )
        if not self.env.context.get("allow_posting"):
            from ..services.closing import check_locked

            for row in moves:
                check_locked(self.env, row)


class AuditLog(BaseModel):
    _name = "accounting.audit_log"
    _table = "audit_log"
    _description = "Posting Audit"
    _order = "-id"

    move_id = f.Many2one("accounting.move", string="Entry")
    action = f.Selection(
        [
            ("post", "Post"),
            ("cancel", "Cancel"),
            ("reverse", "Reverse"),
            ("secure", "Secure"),
        ],
        required=True
    )
    user_id = f.Many2one("core.user", string="User")
    detail = f.Char()
