"""Deterministic demo transactions for the public demo environment.

`kberp init --with-demo` installs the reference data, contacts and products.
This module adds the documents that make the dashboards useful: a draft
quotation, a confirmed sale with a posted and paid invoice, a confirmed
purchase with a completed receipt and a posted bill, and a draft RFQ.

The seed is idempotent: the confirmed sale carries a fixed marker in its
`reference` field, and a second run returns without writing anything. It is
only called by `kberp demo` / `make demo`, never by the installer, so tests and
normal installations keep a clean baseline.
"""

from __future__ import annotations

from typing import Any

from .addons.accounting.services.payments import register_payment
from .addons.inventory.services import api as stock
from .env import Env
from .services.actions import invoke

MARKER = "DEMO-SO-001"


class DemoError(RuntimeError):
    """The demo seed cannot run because base reference data is missing."""


def _one(env: Env, model: str, domain: list[Any], label: str) -> int:
    ids = env[model].search(domain, limit=1)
    if not ids:
        raise DemoError(f"demo data is missing the {label}")
    return ids[0]


def _products(env: Env) -> dict[str, int]:
    ids = env["core.product_template"].search(
        [("default_code", "in", ["PLT-001", "SRV-001", "TAPE-001"])]
    )
    rows = env["core.product_template"].read(ids)
    by_code = {row["default_code"]: row["id"] for row in rows}
    missing = {"PLT-001", "SRV-001", "TAPE-001"} - set(by_code)
    if missing:
        raise DemoError(f"demo data is missing products: {', '.join(sorted(missing))}")
    return by_code


def _customer(env: Env) -> int:
    return _one(env, "core.partner", [("name", "=", "Acme Trading")], "customer Acme Trading")


def _vendor(env: Env) -> int:
    return _one(env, "core.partner", [("name", "=", "Demo Supplier")], "vendor Demo Supplier")


def seed(env: Env) -> dict[str, Any]:
    """Create the demo document chain and return the document names.

    The caller owns the connection. Re-running is safe and returns
    `{"seeded": False}` when the marker document already exists.
    """
    with env.db.transaction():
        orders = env["sales.order"]
        if orders.search([("reference", "=", MARKER)], limit=1):
            return {"seeded": False}

        customer_id = _customer(env)
        vendor_id = _vendor(env)
        products = _products(env)

        quotation_id = orders.create(
            {
                "partner_id": customer_id,
                "reference": "DEMO-QUOTE-001",
                "note": "Draft quotation for the demo tour.",
                "order_line": [
                    {
                        "product_id": products["TAPE-001"],
                        "name": "Packing tape",
                        "qty": 20,
                        "price_unit": 180,
                    }
                ],
            }
        )

        order_id = orders.create(
            {
                "partner_id": customer_id,
                "reference": MARKER,
                "note": "Confirmed sale used by the demo dashboard.",
                "order_line": [
                    {
                        "product_id": products["PLT-001"],
                        "name": "Warehouse pallets",
                        "qty": 4,
                        "price_unit": 2500,
                    }
                ],
            }
        )
        invoke(env, "sales.order", "action_confirm", order_id)
        invoice_id = invoke(env, "sales.order", "action_invoice", order_id)["invoice_id"]
        invoke(env, "accounting.move", "action_post", invoice_id)

        invoice = env["accounting.move"].read([invoice_id])[0]
        bank_journal = _one(
            env, "accounting.journal", [("code", "=", "BNK")], "bank journal"
        )
        payment = register_payment(
            env,
            invoice_id,
            amount=invoice["amount_total"],
            journal_id=bank_journal,
            memo="Demo customer payment",
        )

        purchase_orders = env["purchase.order"]
        rfq_id = purchase_orders.create(
            {
                "partner_id": vendor_id,
                "reference": "DEMO-RFQ-001",
                "order_line": [
                    {
                        "product_id": products["SRV-001"],
                        "name": "Logistics service",
                        "qty": 1,
                        "price_unit": 15000,
                    }
                ],
            }
        )

        po_id = purchase_orders.create(
            {
                "partner_id": vendor_id,
                "reference": "DEMO-PO-001",
                "order_line": [
                    {
                        "product_id": products["PLT-001"],
                        "name": "Warehouse pallets",
                        "qty": 10,
                        "price_unit": 900,
                    }
                ],
            }
        )
        invoke(env, "purchase.order", "action_confirm", po_id)
        po = purchase_orders.read([po_id])[0]

        picking_id = _one(
            env,
            "inventory.picking",
            [("origin", "=", po["name"]), ("picking_type", "=", "in")],
            f"receipt for {po['name']}",
        )
        move_id = _one(
            env, "inventory.move", [("picking_id", "=", picking_id)], "receipt line"
        )
        stock.set_done(env, move_id, 10)
        stock.validate(env, picking_id)

        bill_id = invoke(env, "purchase.order", "action_create_bill", po_id)["bill_id"]
        invoke(env, "accounting.move", "action_post", bill_id)

        def name(model: str, record_id: int) -> str:
            return env[model].read([record_id])[0]["name"]

        return {
            "seeded": True,
            "quotation": name("sales.order", quotation_id),
            "sales_order": name("sales.order", order_id),
            "invoice": name("accounting.move", invoice_id),
            "payment": payment["message"],
            "rfq": name("purchase.order", rfq_id),
            "purchase_order": po["name"],
            "receipt": name("inventory.picking", picking_id),
            "bill": name("accounting.move", bill_id),
        }
