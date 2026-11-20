"""Requests for quotation and purchase orders."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ....orm import fields as f
from ....orm.model import BaseModel, ValidationError

CENT = Decimal("0.01")


class Settings(BaseModel):
    _name = "purchase.settings"
    _table = "settings"
    _description = "Purchase Settings"
    _rec_name = "name"
    _unique_together = (("company_id",),)

    xml_id = f.Char(index=True)
    name = f.Char(default="Purchase Settings", required=True)
    company_id = f.Many2one("core.company", string="Company")
    bill_control = f.Selection(
        [("ordered", "Ordered quantities"), ("received", "Received quantities")],
        default="ordered",
        string="Bill Control",
    )
    lock_confirmed = f.Boolean(default=False, string="Lock Confirmed Orders")
    show_warnings = f.Boolean(default=True, string="Show Vendor Warnings")
    approval_threshold = f.Monetary(default=0, string="Approval Threshold")
    receipt_reminder_days = f.Integer(default=3, string="Receipt Reminder (days)")
    landed_cost_account_id = f.Many2one(
        "accounting.account", string="Landed Cost Account"
    )


class VendorPrice(BaseModel):
    _name = "purchase.vendor_price"
    _table = "vendor_price"
    _description = "Vendor Price"
    _rec_name = "name"
    _order = "-min_qty, -id"

    name = f.Char(required=True)
    partner_id = f.Many2one("core.partner", string="Vendor", required=True, index=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True, index=True)
    min_qty = f.Float(default=0, string="Minimum Quantity")
    price = f.Monetary(default=0)
    currency_id = f.Many2one("core.currency", string="Currency")
    lead_time = f.Integer(default=0, string="Lead Time (days)")
    date_start = f.Date(string="Valid From")
    date_end = f.Date(string="Valid To")
    active = f.Boolean(default=True)


class PurchaseOrder(BaseModel):
    _name = "purchase.order"
    _table = "order"
    _description = "Request for Quotation"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True, index=True, string="Number")
    partner_id = f.Many2one("core.partner", string="Vendor", required=True, index=True)
    currency_id = f.Many2one("core.currency", string="Currency")
    payment_term = f.Char(string="Payment Terms")
    buyer_id = f.Many2one("core.user", string="Buyer")
    expected_date = f.Date(string="Expected Arrival")
    incoterm = f.Char(string="Incoterm")
    reference = f.Char(string="Vendor Reference")
    origin = f.Char(string="Source Document", index=True)
    agreement_id = f.Many2one("purchase.agreement", string="Agreement", index=True)
    approval_state = f.Selection(
        [
            ("not_required", "Not Required"),
            ("waiting", "Waiting Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="not_required",
        string="Approval",
    )
    approved_by = f.Many2one("core.user", string="Approved By")
    approved_date = f.Datetime(string="Approved On")
    approval_note = f.Char(string="Approval Note")
    state = f.Selection(
        [
            ("draft", "RFQ"),
            ("sent", "RFQ Sent"),
            ("purchase", "Purchase Order"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
    )
    date_order = f.Datetime(string="Order Date")
    amount_untaxed = f.Monetary(default=0, string="Untaxed")
    amount_tax = f.Monetary(default=0, string="Taxes")
    amount_total = f.Monetary(default=0, string="Total")
    receipt_status = f.Selection(
        [
            ("nothing", "Not Received"),
            ("partial", "Partially Received"),
            ("full", "Fully Received"),
        ],
        default="nothing",
    )
    invoice_status = f.Selection(
        [
            ("nothing", "Nothing to Bill"),
            ("waiting", "Waiting Bills"),
            ("full", "Fully Billed"),
        ],
        default="nothing",
    )
    bill_control = f.Selection(
        [("ordered", "Ordered quantities"), ("received", "Received quantities")],
        default="ordered",
        string="Bill Control",
    )
    qty_received = f.Float(default=0, string="Received")
    qty_billed = f.Float(default=0, string="Billed")
    locked = f.Boolean(default=False, string="Locked")
    warning = f.Text()
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)
    note = f.Text(string="Terms and Conditions")
    order_line = f.One2many("purchase.order_line", "order_id", string="Order Lines")

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        self._fill_defaults(values)
        lines = self._one2many_values(values)
        for name, (_field, children) in lines.items():
            values[name] = self._fill_lines(children, values.get("partner_id"))
        record_id = super().create(values)
        self._recompute([record_id])
        return record_id

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        if values.get("state") == "purchase" and not self.env.context.get(
            "allow_confirmed"
        ):
            raise ValidationError(
                "confirm the order through the Confirm button so approvals and receipts stay in step"
            )
        if not self.env.context.get("allow_locked"):
            for row in self.read([int(record_id) for record_id in ids]):
                if row["locked"]:
                    raise ValidationError(
                        f"purchase order {row['name']} is locked. Only chatter notes can be added."
                    )
        values = dict(values)
        lines = self._one2many_values(values)
        for name, (_field, children) in lines.items():
            values[name] = self._fill_lines(children, values.get("partner_id"))
        updated = super().write(ids, values)
        if not self.env.context.get("skip_totals"):
            self._recompute([int(record_id) for record_id in ids])
        return updated

    def _default_company_id(self) -> int | None:
        company_id = (self.env.user or {}).get("company_id")
        if not company_id:
            companies = self.env["core.company"].search([], limit=1)
            company_id = companies[0] if companies else None
        return int(company_id) if company_id else None

    def _fill_defaults(self, values: dict[str, Any]) -> None:
        if not values.get("company_id"):
            values["company_id"] = self._default_company_id()
        if not values.get("name"):
            year = dt.datetime.now(dt.UTC).year
            number = self.env["core.ir_sequence"].next_code("purchase.seq_purchase_order")
            values["name"] = f"PO/{year}/{number}"
        if not values.get("currency_id"):
            settings_id = self.env["purchase.settings"].search([], limit=1)
            if settings_id:
                company = self.env["purchase.settings"].read([settings_id[0]])[0]
                company_id = (
                    (company.get("company_id") or {}).get("id")
                    or values.get("company_id")
                    or self._default_company_id()
                )
            else:
                company_id = values.get("company_id") or self._default_company_id()
            if company_id:
                company = self.env["core.company"].read([int(company_id)])
                if company:
                    currency = company[0].get("currency_id") or {}
                    values["currency_id"] = (
                        currency.get("id") if isinstance(currency, dict) else currency
                    )
        if not values.get("buyer_id") and self.env.uid:
            values["buyer_id"] = self.env.uid
        if not values.get("bill_control"):
            settings_ids = self.env["purchase.settings"].search([], limit=1)
            if settings_ids:
                settings = self.env["purchase.settings"].read([settings_ids[0]])[0]
                values["bill_control"] = settings.get("bill_control") or "ordered"

    def _fill_lines(
        self, children: list[dict[str, Any]], partner_id: Any
    ) -> list[dict[str, Any]]:
        from ..services.vendor_pricing import vendor_price

        result = []
        for index, line in enumerate(children):
            line = dict(line)
            filled = [
                line.get(field)
                for field in ("product_id", "name", "price_unit", "qty")
                if line.get(field) not in (None, "", 0, "0")
            ]
            if not filled:
                continue
            product_id = line.get("product_id")
            if product_id:
                product = self.env["core.product_template"].read([int(product_id)])
                if product:
                    if not line.get("name"):
                        line["name"] = product[0]["name"]
                    if not line.get("uom_id"):
                        uom = product[0].get("uom_id") or {}
                        line["uom_id"] = uom.get("id") if isinstance(uom, dict) else uom
                    if not line.get("price_unit") and partner_id:
                        price = vendor_price(
                            self.env,
                            partner_id=int(partner_id),
                            product_id=int(product_id),
                            qty=float(line.get("qty") or 1),
                        )
                        if price:
                            line["price_unit"] = price["price"]
                            line["lead_time"] = price["lead_time"]
            if not line.get("price_unit") and product_id:
                product = self.env["core.product_template"].read([int(product_id)])
                if product:
                    line["price_unit"] = product[0].get("standard_price") or 0
            if not line.get("sequence"):
                line["sequence"] = (index + 1) * 10
            result.append(line)
        return result

    def _recompute(self, ids: list[int]) -> None:
        if not ids or self.env.context.get("skip_totals"):
            return
        from ..services.pricing import recompute_totals

        recompute_totals(self.env, ids)


class PurchaseOrderLine(BaseModel):
    _name = "purchase.order_line"
    _table = "order_line"
    _description = "Purchase Order Line"
    _order = "sequence, id"

    order_id = f.Many2one("purchase.order", string="Order", required=True, index=True)
    sequence = f.Integer(default=10)
    product_id = f.Many2one("core.product_template", string="Product")
    name = f.Char(required=True)
    qty = f.Float(default=1, string="Quantity")
    uom_id = f.Many2one("core.uom", string="Unit of Measure")
    price_unit = f.Monetary(default=0, string="Unit Price")
    tax_ids = f.Many2many("accounting.tax", string="Taxes")
    subtotal = f.Monetary(default=0, string="Subtotal")
    qty_received = f.Float(default=0, string="Received")
    qty_billed = f.Float(default=0, string="Billed")
    lead_time = f.Integer(default=0, string="Lead Time")
    agreement_line_id = f.Many2one(
        "purchase.agreement_line", string="Agreement Line", index=True
    )
    note = f.Char()
