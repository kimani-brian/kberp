#!/usr/bin/env python
"""Top-list benchmark: search + read p95 across the business list views.

Run after `make init --with-demo`:

    .venv/bin/python scripts/bench_lists.py

Seeds 10,000 partners (the largest list in the seed), then times the model
path each list action uses. Fails when any list exceeds 800 ms p95 or when the
query count grows with the number of rows.
"""

from __future__ import annotations

import statistics
import sys
import time

from bench_list import PARTNERS, seed

from kberp.config import Settings
from kberp.db import Database
from kberp.env import Env
from kberp.registry import Registry

RUNS = 10
BUDGET_MS = 800
LIST_LIMIT = 80
# Kernel metadata and report projections are settings/technical screens, not
# the operational lists the NFR measures.
SKIP = {
    "core.ir_ui_menu",
    "core.ir_ui_view",
    "core.ir_act_window",
    "core.ir_act_client",
    "core.ir_model_access",
    "core.ir_rule",
    "core.ir_sequence",
    "core.ir_module",
    "accounting.report",
    "accounting.report_line",
    "platform.outbox_event",
    "platform.bus_message",
    "chatter.message",
    "chatter.activity",
}


def list_models(env: Env, limit: int = 20) -> list[str]:
    actions = env["core.ir_act_window"].read(env["core.ir_act_window"].search([], order="id"))
    seen: list[str] = []
    for action in actions:
        model = action["res_model"]
        if model in SKIP or model in seen or "list" not in (action["view_mode"] or ""):
            continue
        if model not in env.registry.models:
            continue
        seen.append(model)
        if len(seen) == limit:
            break
    return seen


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings)
    db.open()
    try:
        registry = Registry(settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        seed(db)

        queries: list[str] = []
        original = db.fetch_all

        def counting(query, params=None):
            queries.append(str(query))
            return original(query, params)

        db.fetch_all = counting  # type: ignore[method-assign]
        results: list[tuple[str, float, float]] = []
        failures: list[str] = []
        for model_name in list_models(env):
            model = env[model_name]
            total = model.search_count([])
            if not total:
                continue

            # Query budget: the number of statements per list must not depend
            # on the number of rows. Small pages can skip label queries for
            # null relations, so compare a full page with the maximum page.
            before = len(queries)
            for _ in range(3):
                model.read(model.search([], limit=LIST_LIMIT))
            baseline = (len(queries) - before) / 3
            before = len(queries)
            model.read(model.search([], limit=500))
            large = len(queries) - before

            timings: list[float] = []
            before = len(queries)
            for _ in range(RUNS):
                start = time.perf_counter()
                ids = model.search([], limit=LIST_LIMIT)
                model.read(ids)
                timings.append((time.perf_counter() - start) * 1000)
            p50 = statistics.median(timings)
            p95 = sorted(timings)[max(int(len(timings) * 0.95) - 1, 0)]
            results.append((model_name, p50, p95))
            if p95 >= BUDGET_MS:
                failures.append(f"{model_name}: p95 {p95:.1f} ms")
            if large > baseline + 1:
                failures.append(
                    f"{model_name}: {baseline:.1f} -> {large:.1f} queries when the page grows"
                )

        db.fetch_all = original  # type: ignore[method-assign]

        print(f"rows      : {PARTNERS:,} partners seeded")
        print(f"lists     : {len(results)}, limit {LIST_LIMIT}, {RUNS} runs each")
        print(f"{'model':44} {'rows':>7} {'p50':>9} {'p95':>9}")
        for model_name, p50, p95 in sorted(results, key=lambda row: row[2], reverse=True):
            total = env[model_name].search_count([])
            print(f"{model_name:44} {total:>7} {p50:>8.1f}ms {p95:>8.1f}ms")
        if failures:
            print("FAIL: list budgets exceeded", file=sys.stderr)
            for failure in failures:
                print(f"  {failure}", file=sys.stderr)
            return 1
        return 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM core.partner WHERE name LIKE 'Bench %'")
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
