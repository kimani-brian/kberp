"""Replenishment, valuation and configuration records for I3."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class Route(BaseModel):
    _name = "inventory.route"
    _table = "route"
    _description = "Route"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    code = f.Char(index=True)
    active = f.Boolean(default=True)


class Rule(BaseModel):
    _name = "inventory.rule"
    _table = "rule"
    _description = "Pull Rule"
    _order = "sequence, id"

    name = f.Char(required=True)
    route_id = f.Many2one("inventory.route", string="Route", required=True)
    action = f.Selection(
        [("buy", "Buy"), ("internal", "Internal Transfer")], default="buy"
    )
    source_location_id = f.Many2one("inventory.location", string="Source")
    dest_location_id = f.Many2one("inventory.location", string="Destination")
    delay_days = f.Integer(default=0, string="Delay (days)")
    sequence = f.Integer(default=10)
    active = f.Boolean(default=True)


class OrderPoint(BaseModel):
    _name = "inventory.orderpoint"
    _table = "orderpoint"
    _description = "Reordering Rule"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True, index=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True, index=True)
    location_id = f.Many2one("inventory.location", string="Location", required=True)
    route_id = f.Many2one("inventory.route", string="Route")
    min_qty = f.Float(default=0, string="Minimum")
    max_qty = f.Float(default=0, string="Maximum")
    qty_multiple = f.Float(default=1, string="Quantity Multiple")
    active = f.Boolean(default=True)
    last_rfq_id = f.Many2one("purchase.order", string="Last RFQ")


class StorageCategory(BaseModel):
    _name = "inventory.storage_category"
    _table = "storage_category"
    _description = "Storage Category"
    _rec_name = "name"

    name = f.Char(required=True)
    max_weight = f.Float(default=0)


class PutawayRule(BaseModel):
    _name = "inventory.putaway_rule"
    _table = "putaway_rule"
    _description = "Putaway Rule"
    _order = "sequence, id"

    name = f.Char(required=True)
    product_id = f.Many2one("core.product_template", string="Product")
    category_id = f.Many2one("inventory.storage_category", string="Storage Category")
    location_id = f.Many2one("inventory.location", string="Suggested Location", required=True)
    package_type_id = f.Many2one("inventory.package_type", string="Package Type")
    sequence = f.Integer(default=10)
    active = f.Boolean(default=True)


class BarcodeNomenclature(BaseModel):
    _name = "inventory.barcode_nomenclature"
    _table = "barcode_nomenclature"
    _description = "Barcode Nomenclature"
    _rec_name = "name"

    name = f.Char(required=True)
    prefix = f.Char()
    lot_separator = f.Char(default="L", size=4)
    qty_separator = f.Char(default="Q", size=4)
    active = f.Boolean(default=True)


class DeliveryMethod(BaseModel):
    _name = "inventory.delivery_method"
    _table = "delivery_method"
    _description = "Delivery Method"
    _rec_name = "name"

    name = f.Char(required=True)
    code = f.Char(index=True)
    active = f.Boolean(default=True)


class ZipPrefix(BaseModel):
    _name = "inventory.zip_prefix"
    _table = "zip_prefix"
    _description = "Zip Prefix"
    _rec_name = "name"

    name = f.Char(required=True)
    prefix = f.Char(required=True, index=True)
    delivery_method_id = f.Many2one("inventory.delivery_method", string="Delivery Method")


class ValuationLayer(BaseModel):
    _name = "inventory.valuation_layer"
    _table = "valuation_layer"
    _description = "Valuation Layer"
    _order = "id"
    _unique_together = (("move_id",),)

    move_id = f.Many2one("inventory.move", string="Stock Move", required=True, index=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True)
    qty = f.Float(default=0)
    value = f.Monetary(default=0)
    kind = f.Selection(
        [("in", "Stock In"), ("out", "Stock Out"), ("scrap", "Scrap"), ("adjust", "Adjustment")],
        default="in",
    )
    valuation_move_id = f.Many2one("accounting.move", string="Accounting Entry")
