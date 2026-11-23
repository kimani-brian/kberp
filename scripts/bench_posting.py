#!/usr/bin/env python
"""Posting benchmark: confirm a 50-line quotation and measure p95.

Run after `make init --with-demo`:

    .venv/bin/python scripts/bench_posting.py

The target from `prd.md` §2.3 is p95 < 1500 ms for a 50-line document. The
script creates its own orders, confirms them through the same service the UI
calls, and cleans up afterwards so it is safe to repeat.
"""

from __future__ import annotations

import statistics
import sys
import time

from kberp.config import Settings
from kberp.db import Database
from kberp.env import Env
from kberp.registry import Registry
from kberp.services.actions import invoke

LINES = 50
RUNS = 20
BUDGET_MS = 1500
PREFIX = "BENCH-POST"


def _ids(value) -> int | None:
    if isinstance(value, dict):
        return value.get("id")
    return value


def create_order(env: Env, index: int) -> int:
    order = env["sales.order"]
    company = env["core.company"].search([], limit=1)
    partners = env["core.partner"].search([("is_company", "=", True)], limit=1)
    if not partners:
        partners = env["core.partner"].search([], limit=1)
    products = env["core.product_template"].search([], limit=LINES)
    if not company or not partners or not products:
        raise SystemExit("run `kberp init --with-demo` before benchmarking")

    order_id = order.create(
        {
            "name": f"{PREFIX}-{index:03d}",
            "partner_id": partners[0],
            "company_id": company[0],
            "state": "draft",
        }
    )
    line = env["sales.order_line"]
    for number, product_id in enumerate(products, start=1):
        product = env["core.product_template"].read([product_id])[0]
        line.create(
            {
                "order_id": order_id,
                "sequence": number,
                "product_id": product_id,
                "name": product["name"],
                "qty": 1,
                "price_unit": product.get("list_price") or 10,
                "uom_id": _ids(product.get("uom_id")),
            }
        )
    return order_id


def cleanup(db: Database) -> None:
    with db.cursor() as cur:
        cur.execute("DELETE FROM inventory.move_line WHERE move_id IN (SELECT id FROM inventory.move WHERE picking_id IN (SELECT id FROM inventory.picking WHERE origin LIKE %s))", (f"{PREFIX}%",))
        cur.execute("DELETE FROM inventory.move WHERE picking_id IN (SELECT id FROM inventory.picking WHERE origin LIKE %s)", (f"{PREFIX}%",))
        cur.execute("DELETE FROM inventory.picking WHERE origin LIKE %s", (f"{PREFIX}%",))
        cur.execute(
            'DELETE FROM sales."order_line" WHERE order_id IN '
            '(SELECT id FROM sales."order" WHERE name LIKE %s)',
            (f"{PREFIX}%",),
        )
        cur.execute('DELETE FROM sales."order" WHERE name LIKE %s', (f"{PREFIX}%",))
        cur.execute("DELETE FROM platform.outbox_event WHERE payload::text LIKE %s", (f"%{PREFIX}%",))


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings)
    db.open()
    try:
        registry = Registry(settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        cleanup(db)

        timings: list[float] = []
        for index in range(1, RUNS + 1):
            order_id = create_order(env, index)
            start = time.perf_counter()
            result = invoke(env, "sales.order", "action_confirm", order_id)
            timings.append((time.perf_counter() - start) * 1000)
            assert result.get("state") == "sale", result

        p50 = statistics.median(timings)
        p95 = sorted(timings)[max(int(len(timings) * 0.95) - 1, 0)]
        print(f"lines     : {LINES}")
        print(f"runs      : {RUNS}")
        print(f"p50       : {p50:.1f} ms")
        print(f"p95       : {p95:.1f} ms (budget {BUDGET_MS} ms)")
        if p95 >= BUDGET_MS:
            print("FAIL: confirm exceeded the posting budget", file=sys.stderr)
            return 1
        return 0
    finally:
        cleanup(db)
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
