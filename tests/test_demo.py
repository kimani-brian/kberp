"""The scripted demo chain must build, balance and stay idempotent."""

from __future__ import annotations

import pytest

from kberp.demo import MARKER, seed


class _Rollback(Exception):
    """End the outer transaction without committing demo rows to the test DB."""


def test_demo_seed_builds_the_chain_and_is_idempotent(env):
    with pytest.raises(_Rollback), env.db.transaction():
        summary = seed(env)

        assert summary["seeded"] is True
        assert summary["quotation"] != summary["sales_order"]
        assert summary["invoice"].startswith("SAL/")
        assert summary["bill"].startswith("PUR/")

        sale = env["sales.order"].read(
            env["sales.order"].search([("reference", "=", MARKER)], limit=1)
        )[0]
        assert sale["state"] == "sale"
        assert sale["invoice_status"] == "fully invoiced"

        invoice = env["accounting.move"].read(
            env["accounting.move"].search(
                [("origin", "=", sale["name"]), ("move_type", "=", "out_invoice")],
                limit=1,
            )
        )[0]
        assert invoice["state"] == "posted"
        assert invoice["payment_state"] == "paid"

        purchase = env["purchase.order"].read(
            env["purchase.order"].search([("reference", "=", "DEMO-PO-001")], limit=1)
        )[0]
        assert purchase["state"] == "purchase"
        assert purchase["receipt_status"] == "full"
        assert purchase["invoice_status"] == "full"

        receipt = env["inventory.picking"].search(
            [("origin", "=", purchase["name"]), ("picking_type", "=", "in")], limit=1
        )
        assert receipt
        assert env["inventory.picking"].read(receipt)[0]["state"] == "done"

        bill = env["accounting.move"].read(
            env["accounting.move"].search(
                [("origin", "=", purchase["name"]), ("move_type", "=", "in_invoice")],
                limit=1,
            )
        )[0]
        assert bill["state"] == "posted"
        assert bill["payment_state"] == "not paid"

        assert seed(env) == {"seeded": False}
        raise _Rollback
