"""Quotations and sales orders.

State changes live in `sales.services.orders`; the model only materialises
defaults, keeps the document number unique and asks the pricing service to
refresh stored totals after a save.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....orm import fields as f
from ....orm.model import BaseModel, ValidationError


class SaleOrder(BaseModel):
    _name = "sales.order"
    _table = "order"
    _description = "Quotation"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True, index=True, string="Number")
    partner_id = f.Many2one("core.partner", string="Customer", required=True, index=True)
    invoice_address_id = f.Many2one("core.partner", string="Invoice Address")
    delivery_address_id = f.Many2one("core.partner", string="Delivery Address")
    pricelist_id = f.Many2one("core.pricelist", string="Pricelist")
    payment_term = f.Char(string="Payment Terms")
    currency_id = f.Many2one("core.currency", string="Currency")
    validity_date = f.Date(string="Expiration")
    salesperson_id = f.Many2one("core.user", string="Salesperson")
    reference = f.Char(string="Customer Reference")
    state = f.Selection(
        [
            ("draft", "Quotation"),
            ("sent", "Quotation Sent"),
            ("sale", "Sales Order"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
    )
    date_order = f.Datetime(string="Order Date")
    amount_untaxed = f.Monetary(default=0, string="Untaxed")
    amount_tax = f.Monetary(default=0, string="Taxes")
    amount_total = f.Monetary(default=0, string="Total")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)
    note = f.Text(string="Terms and Conditions")
    invoice_policy = f.Selection(
        [("ordered", "Ordered quantities"), ("delivered", "Delivered quantities")],
        default="ordered",
        string="Invoicing Policy",
    )
    invoice_status = f.Selection(
        [
            ("nothing", "Nothing to Invoice"),
            ("to invoice", "To Invoice"),
            ("fully invoiced", "Fully Invoiced"),
            ("upselling", "Upselling Opportunity"),
        ],
        default="nothing",
    )
    qty_delivered = f.Float(default=0, string="Delivered")
    qty_invoiced = f.Float(default=0, string="Invoiced")
    locked = f.Boolean(default=False, string="Locked")
    tag_ids = f.Many2many("sales.tag", string="Tags")
    order_line = f.One2many("sales.order_line", "order_id", string="Order Lines")

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        self._fill_defaults(values)
        lines = self._one2many_values(values)
        for name, (_field, children) in lines.items():
            values[name] = self._fill_lines(children, values.get("pricelist_id"))
        record_id = super().create(values)
        self._recompute([record_id])
        return record_id

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        if not self.env.context.get("allow_locked"):
            for row in self.read([int(record_id) for record_id in ids]):
                if row["locked"]:
                    raise ValidationError(
                        f"order {row['name']} is locked. Only chatter notes can be added."
                    )
        values = dict(values)
        lines = self._one2many_values(values)
        for name, (_field, children) in lines.items():
            values[name] = self._fill_lines(children, values.get("pricelist_id"))
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
            number = self.env["core.ir_sequence"].next_code("sales.seq_sales_order")
            values["name"] = f"SO/{year}/{number}"
        partner_id = values.get("partner_id")
        if partner_id:
            partner = self.env["core.partner"].read([int(partner_id)])
            if partner:
                row = partner[0]
                values.setdefault(
                    "salesperson_id", (row.get("salesperson_id") or {}).get("id")
                )
                addresses = self.env["core.partner"].address_get(
                    int(partner_id), ["invoice", "delivery"]
                )
                values.setdefault("invoice_address_id", addresses.get("invoice"))
                values.setdefault("delivery_address_id", addresses.get("delivery"))
        if not values.get("salesperson_id"):
            salespeople = self.env["core.user"].search([], limit=1)
            if salespeople:
                values["salesperson_id"] = self.env.uid or salespeople[0]
        pricelist_id = values.get("pricelist_id")
        if not pricelist_id:
            lists = self.env["core.pricelist"].search([("active", "=", True)], limit=1)
            if lists:
                pricelist_id = lists[0]
                values["pricelist_id"] = pricelist_id
        if not values.get("currency_id") and pricelist_id:
            pricelist = self.env["core.pricelist"].read([int(pricelist_id)])
            if pricelist:
                values["currency_id"] = (pricelist[0].get("currency_id") or {}).get("id")
        if not values.get("currency_id"):
            company_id = values.get("company_id") or self._default_company_id()
            if company_id:
                company = self.env["core.company"].read([int(company_id)])
                if company:
                    currency = company[0].get("currency_id")
                    values["currency_id"] = (
                        currency.get("id") if isinstance(currency, dict) else currency
                    )
        if not values.get("validity_date"):
            settings = self.env["sales.settings"].search([], limit=1)
            days = (
                self.env["sales.settings"].read([settings[0]])[0]["validity_days"]
                if settings
                else 30
            )
            values["validity_date"] = dt.date.today() + dt.timedelta(days=days)

    def _fill_lines(
        self, children: list[dict[str, Any]], pricelist_id: Any
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index, line in enumerate(children):
            line = dict(line)
            filled = [
                line.get(field)
                for field in ("product_id", "name", "price_unit", "qty")
                if line.get(field) not in (None, "", 0, "0")
            ]
            if not filled:
                continue
            if line.get("product_id") and (not line.get("name") or not line.get("price_unit")):
                product = self.env["core.product_template"].read([int(line["product_id"])])
                if product:
                    row = product[0]
                    if not line.get("name"):
                        line["name"] = row.get("name")
                    if not line.get("uom_id"):
                        line["uom_id"] = (row.get("uom_id") or {}).get("id")
                    if not line.get("price_unit"):
                        line["price_unit"] = row.get("list_price") or 0
            if not line.get("sequence"):
                line["sequence"] = (index + 1) * 10
            result.append(line)
        return result

    def _recompute(self, ids: list[int]) -> None:
        if not ids or self.env.context.get("skip_totals"):
            return
        from ..services.pricing import recompute_totals

        recompute_totals(self.env, ids)


class SaleOrderLine(BaseModel):
    _name = "sales.order_line"
    _table = "order_line"
    _description = "Order Line"
    _order = "sequence, id"

    order_id = f.Many2one("sales.order", string="Order", required=True, index=True)
    sequence = f.Integer(default=10)
    product_id = f.Many2one("core.product_template", string="Product")
    name = f.Char(required=True)
    qty = f.Float(default=1, string="Quantity")
    uom_id = f.Many2one("core.uom", string="Unit of Measure")
    price_unit = f.Monetary(default=0, string="Unit Price")
    discount = f.Float(default=0, string="Discount (%)")
    tax_ids = f.Many2many("accounting.tax", string="Taxes")
    subtotal = f.Monetary(default=0, string="Subtotal")
    qty_delivered = f.Float(default=0, string="Delivered")
    qty_invoiced = f.Float(default=0, string="Invoiced")
    note = f.Char()
