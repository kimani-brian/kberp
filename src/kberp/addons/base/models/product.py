"""Kernel catalogue: currencies, units of measure, product categories and products."""

from __future__ import annotations

from ....orm import fields as f
from ....orm.model import BaseModel


class Company(BaseModel):
    _name = "core.company"
    _table = "company"
    _description = "Company"
    _rec_name = "name"

    name = f.Char(required=True)
    currency_id = f.Many2one("core.currency", string="Currency")
    vat = f.Char(string="Tax ID")


class Currency(BaseModel):
    _name = "core.currency"
    _table = "currency"
    _description = "Currency"
    _rec_name = "name"
    _order = "code"

    code = f.Char(required=True, size=3, index=True)
    name = f.Char(required=True)
    symbol = f.Char()
    decimal_places = f.Integer(default=2)
    rate = f.Float(default=1.0, string="Rate")


class Pricelist(BaseModel):
    """A minimal currency-bearing price list.

    S1 only uses it to freeze the order currency. Price rules, dates and formula
    lines belong to S3.
    """

    _name = "core.pricelist"
    _table = "pricelist"
    _description = "Pricelist"
    _rec_name = "name"
    _order = "name"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    currency_id = f.Many2one("core.currency", string="Currency")
    active = f.Boolean(default=True)


class UomCategory(BaseModel):
    _name = "core.uom_category"
    _table = "uom_category"
    _description = "Unit of Measure Category"

    name = f.Char(required=True)


class Uom(BaseModel):
    _name = "core.uom"
    _table = "uom"
    _description = "Unit of Measure"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    category_id = f.Many2one("core.uom_category", string="Category")
    rounding = f.Float(default=1.0)


class ProductCategory(BaseModel):
    _name = "core.product_category"
    _table = "product_category"
    _description = "Product Category"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    parent_id = f.Many2one("core.product_category", string="Parent Category")


class ProductAttribute(BaseModel):
    _name = "core.product_attribute"
    _table = "product_attribute"
    _description = "Product Attribute"
    _rec_name = "name"
    _order = "sequence, name"

    name = f.Char(required=True)
    sequence = f.Integer(default=10)
    display_type = f.Selection(
        [("radio", "Radio"), ("select", "Dropdown"), ("color", "Color")],
        default="radio",
    )
    active = f.Boolean(default=True)
    value_ids = f.One2many(
        "core.product_attribute_value", "attribute_id", string="Values"
    )


class ProductAttributeValue(BaseModel):
    _name = "core.product_attribute_value"
    _table = "product_attribute_value"
    _description = "Product Attribute Value"
    _rec_name = "name"
    _order = "sequence, id"

    attribute_id = f.Many2one(
        "core.product_attribute", string="Attribute", required=True
    )
    name = f.Char(required=True)
    sequence = f.Integer(default=10)
    active = f.Boolean(default=True)


class ProductTemplate(BaseModel):
    _name = "core.product_template"
    _table = "product_template"
    _description = "Product"
    _rec_name = "name"
    _order = "name"

    name = f.Char(required=True)
    external_id = f.Char(string="External ID", index=True)
    default_code = f.Char(string="Internal Reference", index=True)
    type = f.Selection(
        [("goods", "Goods"), ("service", "Service")], default="goods", string="Product Type"
    )
    list_price = f.Monetary(string="Sales Price", default=0)
    standard_price = f.Monetary(string="Cost", default=0)
    uom_id = f.Many2one("core.uom", string="Unit of Measure")
    category_id = f.Many2one("core.product_category", string="Product Category")
    barcode = f.Char(string="Barcode")
    active = f.Boolean(default=True)
    description = f.Text(string="Description")
