#!/usr/bin/env python
"""List-path benchmark: p95 for the 40-row partner list on 10,000 rows.

Run after `make init`:

    .venv/bin/python scripts/bench_list.py

Prints p50/p95 wall time for the model path the list view uses (search + read,
including m2o expansion) and fails if p95 exceeds 800 ms or the path looks N+1.
"""

from __future__ import annotations

import statistics
import sys
import time

from kberp.config import Settings
from kberp.db import Database
from kberp.env import Env
from kberp.registry import Registry

PARTNERS = 10_000
RUNS = 30
BUDGET_MS = 800
# Constant per load: search, read, one label query per many2one and one per
# many2many on the list. The number must not grow with the row count.
MAX_QUERIES = 12


def seed(db: Database) -> int:
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.partner WHERE name LIKE 'Bench %'")
        cur.execute(
            """
            INSERT INTO core.partner
                (name, is_company, type, active, email, city, country_id,
                 create_uid, create_date, write_uid, write_date)
            SELECT 'Bench ' || lpad(g::text, 5, '0'),
                   g %% 5 = 0,
                   'contact',
                   true,
                   'bench' || g || '@example.test',
                   'Nairobi',
                   (SELECT id FROM core.country WHERE code = 'KE' LIMIT 1),
                   1, now(), 1, now()
              FROM generate_series(1, %s) AS g
            """,
            (PARTNERS,),
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS partner_name_idx ON core.partner (name)"
        )
    return PARTNERS


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings)
    db.open()
    try:
        registry = Registry(settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        seed(db)
        partner = env["core.partner"]

        queries: list[str] = []
        original = db.fetch_all

        def counting(query, params=None):
            queries.append(str(query))
            return original(query, params)

        db.fetch_all = counting  # type: ignore[method-assign]

        timings = []
        for _ in range(RUNS):
            start = time.perf_counter()
            ids = partner.search([], order="name", limit=40)
            rows = partner.read(ids)
            timings.append((time.perf_counter() - start) * 1000)
            assert len(rows) == 40

        db.fetch_all = original  # type: ignore[method-assign]

        p50 = statistics.median(timings)
        p95 = sorted(timings)[max(int(len(timings) * 0.95) - 1, 0)]
        print(f"rows      : {PARTNERS:,}")
        print(f"runs      : {RUNS}")
        print(f"p50       : {p50:.1f} ms")
        print(f"p95       : {p95:.1f} ms (budget {BUDGET_MS} ms)")
        print(f"queries   : {len(queries)} for {RUNS} list loads ({len(queries) / RUNS:.1f} per load)")

        ok = p95 < BUDGET_MS and len(queries) / RUNS <= MAX_QUERIES
        if not ok:
            print("FAIL: list path exceeded its budget", file=sys.stderr)
            return 1
        return 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM core.partner WHERE name LIKE 'Bench %'")
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
