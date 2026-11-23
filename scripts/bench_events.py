#!/usr/bin/env python
"""Outbox latency benchmark: emit → handler → processed.

Run after `make init`:

    .venv/bin/python scripts/bench_events.py

The target from `prd.md` §2.3 is a p95 below 5 seconds. The script emits its own
`platform.ping` events and processes them one at a time so the measurement
includes claim, handler and state update.
"""

from __future__ import annotations

import statistics
import sys
import time

from kberp.config import Settings
from kberp.db import Database
from kberp.env import Env
from kberp.registry import Registry
from kberp.services.events import Worker, emit

RUNS = 50
BUDGET_MS = 5000


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings)
    db.open()
    try:
        registry = Registry(settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        events = env["platform.outbox_event"]

        with db.cursor() as cur:
            cur.execute("DELETE FROM platform.outbox_event WHERE event_type = 'platform.ping'")

        worker = Worker(db, registry, batch_size=1)
        # Other events (demo data, earlier runs) can sit in the same queue. Drain
        # them first, otherwise a measured pass may process somebody else's row
        # while our own ping stays pending.
        for _ in range(1000):
            with db.cursor() as cur:
                cur.execute("SELECT count(*) FROM platform.outbox_event WHERE state = 'pending'")
                if cur.fetchone()[0] == 0:
                    break
            if not worker.process_outbox()["processed"]:
                break
        timings: list[float] = []
        for index in range(RUNS):
            event_id = emit(env, "platform.ping", {"seq": index})
            start = time.perf_counter()
            stats = worker.process_outbox()
            timings.append((time.perf_counter() - start) * 1000)
            assert stats["processed"] == 1, stats
            state = events.read([event_id])[0]["state"]
            assert state == "processed", state

        p50 = statistics.median(timings)
        p95 = sorted(timings)[max(int(len(timings) * 0.95) - 1, 0)]
        print(f"events    : {RUNS}")
        print(f"p50       : {p50:.1f} ms")
        print(f"p95       : {p95:.1f} ms (budget {BUDGET_MS} ms)")
        if p95 >= BUDGET_MS:
            print("FAIL: event delivery exceeded its budget", file=sys.stderr)
            return 1
        return 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM platform.outbox_event WHERE event_type = 'platform.ping'")
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
