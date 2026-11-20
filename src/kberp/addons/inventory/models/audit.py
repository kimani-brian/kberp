"""Physical counts, scrap, lots and packages."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ....orm import fields as f
from ....orm.model import BaseModel


class Lot(BaseModel):
    _name = "inventory.lot"
    _table = "lot"
    _description = "Lot / Serial Number"
    _rec_name = "name"
    _order = "name"
    _unique_together = (("product_id", "name", "company_id"),)

    name = f.Char(required=True, index=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True, index=True)
    company_id = f.Many2one("core.company", string="Company")
    expiry_date = f.Date(string="Expiry Date")
    active = f.Boolean(default=True)


class PackageType(BaseModel):
    _name = "inventory.package_type"
    _table = "package_type"
    _description = "Package Type"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    max_weight = f.Float(default=0, string="Max Weight")
    active = f.Boolean(default=True)


class Package(BaseModel):
    _name = "inventory.package"
    _table = "package"
    _description = "Package"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True, index=True)
    package_type_id = f.Many2one("inventory.package_type", string="Package Type")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)


class StockCount(BaseModel):
    _name = "inventory.stock_count"
    _table = "stock_count"
    _description = "Physical Inventory"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True, index=True, string="Number")
    date = f.Date(required=True)
    location_id = f.Many2one("inventory.location", string="Location", required=True)
    company_id = f.Many2one("core.company", string="Company")
    state = f.Selection(
        [("draft", "Draft"), ("done", "Done")], default="draft", required=True
    )
    note = f.Text()
    line_ids = f.One2many("inventory.count_line", "count_id", string="Counted Lines")

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        if not values.get("name"):
            model: Any = self.env["core.ir_sequence"]
            values["name"] = model.next_code("inventory.seq_stock_count")
        values.setdefault("date", dt.date.today())
        location_id = values.get("location_id")
        lines = []
        for line in values.get("line_ids") or []:
            line = dict(line)
            if "expected_qty" not in line and location_id:
                from ..services.api import available_qty

                line["expected_qty"] = available_qty(
                    self.env, int(line["product_id"]), int(location_id)
                )
            lines.append(line)
        values["line_ids"] = lines
        return super().create(values)


class CountLine(BaseModel):
    _name = "inventory.count_line"
    _table = "count_line"
    _description = "Count Line"
    _order = "id"

    count_id = f.Many2one("inventory.stock_count", string="Count", required=True, index=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True)
    lot_id = f.Many2one("inventory.lot", string="Lot / Serial")
    expected_qty = f.Float(default=0, string="Expected")
    counted_qty = f.Float(default=0, string="Counted")
    difference = f.Float(default=0, string="Difference")


class Scrap(BaseModel):
    _name = "inventory.scrap"
    _table = "scrap"
    _description = "Scrap"
    _rec_name = "name"
    _order = "-id"

    name = f.Char(required=True, index=True, string="Number")
    date = f.Date(required=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True)
    qty = f.Float(default=1, string="Quantity")
    location_id = f.Many2one("inventory.location", string="Source Location")
    lot_id = f.Many2one("inventory.lot", string="Lot / Serial")
    reason = f.Char()
    company_id = f.Many2one("core.company", string="Company")
    state = f.Selection(
        [("draft", "Draft"), ("done", "Done")], default="draft", required=True
    )
    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        if not values.get("name"):
            model: Any = self.env["core.ir_sequence"]
            values["name"] = model.next_code("inventory.seq_scrap")
        values.setdefault("date", dt.date.today())
        if not values.get("location_id"):
            locations = self.env["inventory.location"].search(
                [("usage", "=", "internal")], limit=1
            )
            if locations:
                values["location_id"] = locations[0]
        return super().create(values)
