"""Warehouses, locations, quants and stock operations."""

from __future__ import annotations

import uuid
from typing import Any

from ....orm import fields as f
from ....orm.model import BaseModel, ValidationError

USAGES = [
    ("internal", "Internal"),
    ("supplier", "Supplier"),
    ("customer", "Customer"),
    ("inventory", "Inventory Loss"),
    ("production", "Production"),
    ("transit", "Transit"),
]

OPERATIONS = [
    ("incoming", "Receipt"),
    ("outgoing", "Delivery"),
    ("internal", "Internal Transfer"),
]


class Warehouse(BaseModel):
    _name = "inventory.warehouse"
    _table = "warehouse"
    _description = "Warehouse"
    _rec_name = "name"
    _order = "code"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    code = f.Char(required=True, index=True)
    stock_location_id = f.Many2one("inventory.location", string="Stock Location")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)


class Location(BaseModel):
    _name = "inventory.location"
    _table = "location"
    _description = "Location"
    _rec_name = "name"
    _order = "name"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    usage = f.Selection(USAGES, default="internal", required=True)
    parent_id = f.Many2one("inventory.location", string="Parent Location")
    warehouse_id = f.Many2one("inventory.warehouse", string="Warehouse")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)


class OperationType(BaseModel):
    _name = "inventory.operation_type"
    _table = "operation_type"
    _description = "Operation Type"
    _rec_name = "name"
    _order = "code"

    xml_id = f.Char(index=True)
    name = f.Char(required=True)
    code = f.Char(required=True, index=True)
    type = f.Selection(OPERATIONS, required=True)
    sequence_id = f.Many2one("core.ir_sequence", string="Number Sequence")
    source_location_id = f.Many2one("inventory.location", string="Source Location")
    dest_location_id = f.Many2one("inventory.location", string="Destination Location")
    company_id = f.Many2one("core.company", string="Company")
    active = f.Boolean(default=True)


class Quant(BaseModel):
    _name = "inventory.quant"
    _table = "quant"
    _description = "Stock Quant"
    _order = "id"
    _unique_together = (("product_id", "location_id"),)

    product_id = f.Many2one("core.product_template", string="Product", required=True, index=True)
    location_id = f.Many2one("inventory.location", string="Location", required=True, index=True)
    qty = f.Float(default=0, string="On Hand")
    reserved_qty = f.Float(default=0, string="Reserved")
    company_id = f.Many2one("core.company", string="Company")


class Picking(BaseModel):
    _name = "inventory.picking"
    _table = "picking"
    _description = "Transfer"
    _rec_name = "name"
    _order = "-id"
    _unique_together = (("origin", "picking_type"),)

    name = f.Char(required=True, index=True)
    origin = f.Char(string="Source Document", index=True)
    picking_type = f.Selection(
        [("out", "Delivery"), ("in", "Receipt"), ("internal", "Internal Transfer")],
        default="out",
        required=True,
    )
    operation_type_id = f.Many2one("inventory.operation_type", string="Operation Type")
    partner_id = f.Many2one("core.partner", string="Partner", index=True)
    source_location_id = f.Many2one("inventory.location", string="Source Location")
    dest_location_id = f.Many2one("inventory.location", string="Destination Location")
    state = f.Selection(
        [
            ("draft", "Draft"),
            ("assigned", "Ready"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
    )
    scheduled_date = f.Date(string="Scheduled Date")
    company_id = f.Many2one("core.company", string="Company")
    note = f.Text()
    backorder_id = f.Many2one("inventory.picking", string="Backorder of")
    barcode_scan = f.Char(string="Scan Barcode")
    move_ids = f.One2many("inventory.move", "picking_id", string="Operations")

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        if not self.env.context.get("allow_stock"):
            for row in self.read([int(record_id) for record_id in ids]):
                if row["state"] == "done":
                    raise ValidationError(
                        f"done transfer {row['name']} cannot be edited. Reverse it instead."
                    )
        return super().write(ids, values)

    def unlink(self, ids: Any) -> int:
        if not self.env.context.get("allow_stock"):
            for row in self.read([int(record_id) for record_id in ids]):
                if row["state"] == "done":
                    raise ValidationError(
                        f"done transfer {row['name']} cannot be deleted."
                    )
        return super().unlink(ids)

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        operation_id = values.get("operation_type_id")
        if operation_id and not values.get("picking_type"):
            operation = self.env["inventory.operation_type"].read([int(operation_id)])
            if operation:
                values["picking_type"] = {
                    "incoming": "in",
                    "outgoing": "out",
                    "internal": "internal",
                }[operation[0]["type"]]
        if not values.get("name"):
            values["name"] = self._next_transfer_name(operation_id)
        if not values.get("origin"):
            values["origin"] = f"MANUAL/{uuid.uuid4().hex[:8]}"
        record_id = super().create(values)
        self._fill_locations([record_id])
        return record_id

    def _fill_locations(self, ids: list[int]) -> None:
        """Default source and destination from the operation type."""
        for picking in self.read(ids):
            operation = picking.get("operation_type_id") or {}
            operation_id = operation.get("id") if isinstance(operation, dict) else operation
            if not operation_id:
                continue
            op = self.env["inventory.operation_type"].read([int(operation_id)])
            if not op:
                continue
            source = op[0].get("source_location_id") or {}
            destination = op[0].get("dest_location_id") or {}
            source_id = source.get("id") if isinstance(source, dict) else source
            dest_id = destination.get("id") if isinstance(destination, dict) else destination
            values: dict[str, Any] = {}
            if not picking.get("source_location_id") and source_id:
                values["source_location_id"] = source_id
            if not picking.get("dest_location_id") and dest_id:
                values["dest_location_id"] = dest_id
            if values:
                self.write([picking["id"]], values)
            for move in self.env["inventory.move"].read(
                [row["id"] for row in picking.get("move_ids", [])]
            ):
                move_values: dict[str, Any] = {}
                if not move.get("source_location_id") and source_id:
                    move_values["source_location_id"] = source_id
                if not move.get("dest_location_id") and dest_id:
                    move_values["dest_location_id"] = dest_id
                if move_values:
                    self.env["inventory.move"].write([move["id"]], move_values)

    def _next_transfer_name(self, operation_id: Any) -> str:
        if operation_id:
            operation = self.env["inventory.operation_type"].read([int(operation_id)])
            if operation:
                sequence = operation[0].get("sequence_id") or {}
                sequence_id = sequence.get("id") if isinstance(sequence, dict) else sequence
                if sequence_id:
                    model: Any = self.env["core.ir_sequence"]
                    row = model.read([int(sequence_id)])[0]
                    return model.next_code(row["xml_id"])
        return f"TRF/{uuid.uuid4().hex[:8]}"


class Move(BaseModel):
    _name = "inventory.move"
    _table = "move"
    _description = "Stock Move"
    _order = "id"

    picking_id = f.Many2one("inventory.picking", string="Transfer", required=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True)
    name = f.Char(required=True)
    qty = f.Float(default=1, string="Demand")
    done_qty = f.Float(default=0, string="Done")
    uom_id = f.Many2one("core.uom", string="Unit of Measure")
    lot_id = f.Many2one("inventory.lot", string="Lot / Serial")
    package_id = f.Many2one("inventory.package", string="Package")
    source_location_id = f.Many2one("inventory.location", string="Source Location")
    dest_location_id = f.Many2one("inventory.location", string="Destination Location")
    note = f.Char()
    move_line_ids = f.One2many("inventory.move_line", "move_id", string="Detailed Operations")

    def create(self, values: dict[str, Any]) -> int:
        values = dict(values)
        product_id = values.get("product_id")
        if product_id:
            product = self.env["core.product_template"].read([int(product_id)])
            if product:
                if not values.get("name"):
                    values["name"] = product[0]["name"]
                if not values.get("uom_id"):
                    uom = product[0].get("uom_id") or {}
                    values["uom_id"] = uom.get("id") if isinstance(uom, dict) else uom
        return super().create(values)

    def write(self, ids: Any, values: dict[str, Any]) -> int:
        if not self.env.context.get("allow_stock"):
            self._check_mutable(ids)
        return super().write(ids, values)

    def unlink(self, ids: Any) -> int:
        if not self.env.context.get("allow_stock"):
            self._check_mutable(ids)
        return super().unlink(ids)

    def _check_mutable(self, ids: Any) -> None:
        picking_ids = {
            row["picking_id"]["id"]
            for row in self.read([int(record_id) for record_id in ids])
            if row.get("picking_id")
        }
        if not picking_ids:
            return
        for picking in self.env["inventory.picking"].read(list(picking_ids)):
            if picking["state"] == "done":
                raise ValidationError(
                    f"lines of done transfer {picking['name']} cannot be changed."
                )


class MoveLine(BaseModel):
    _name = "inventory.move_line"
    _table = "move_line"
    _description = "Detailed Operation"
    _order = "id"

    move_id = f.Many2one("inventory.move", string="Move", required=True, index=True)
    product_id = f.Many2one("core.product_template", string="Product", required=True)
    quant_id = f.Many2one("inventory.quant", string="Reserved Quant")
    source_location_id = f.Many2one("inventory.location", string="Source Location")
    dest_location_id = f.Many2one("inventory.location", string="Destination Location")
    qty = f.Float(default=0, string="Done")
    uom_id = f.Many2one("core.uom", string="Unit of Measure")
    lot_id = f.Many2one("inventory.lot", string="Lot / Serial")
    package_id = f.Many2one("inventory.package", string="Package")
    note = f.Char()


class Settings(BaseModel):
    _name = "inventory.settings"
    _table = "settings"
    _description = "Inventory Settings"
    _rec_name = "name"
    _unique_together = (("company_id",),)

    xml_id = f.Char(index=True)
    name = f.Char(default="Inventory Settings", required=True)
    company_id = f.Many2one("core.company", string="Company")
    allow_negative_stock = f.Boolean(default=False, string="Allow Negative Stock")
    reservation_method = f.Selection(
        [("manual", "Manual"), ("auto", "Automatic")], default="manual"
    )
    valuation = f.Selection(
        [("periodic", "Periodic"), ("perpetual", "Perpetual")], default="periodic"
    )
    stock_account_id = f.Many2one("accounting.account", string="Stock Account")
    cogs_account_id = f.Many2one("accounting.account", string="COGS Account")
    loss_account_id = f.Many2one("accounting.account", string="Inventory Loss Account")
    valuation_journal_id = f.Many2one("accounting.journal", string="Valuation Journal")
    use_lots = f.Boolean(default=True, string="Track Lots / Serials")
    use_expiry = f.Boolean(default=False, string="Track Expiry Dates")
    use_packages = f.Boolean(default=True, string="Track Packages")
