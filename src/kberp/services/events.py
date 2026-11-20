"""Transactional outbox: emit inside the business transaction, deliver later.

`emit()` writes a row with the same cursor as the caller's transaction, so an
event can never exist for a rolled-back write. The worker claims rows with
`FOR UPDATE SKIP LOCKED`, retries failures and dead-letters after `max_attempts`.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import logging
import traceback
from collections.abc import Callable
from typing import Any

from ..env import Env
from .bus import Bus

log = logging.getLogger(__name__)

Handler = Callable[[Env, dict[str, Any]], None]
_handlers: dict[str, list[Handler]] = {}


def register_handler(event_type: str, handler: Handler) -> None:
    """Subscribe a handler. Called from module import time."""
    _handlers.setdefault(event_type, []).append(handler)


def handlers_for(event_type: str) -> list[Handler]:
    return list(_handlers.get(event_type, []))


def emit(env: Env, event_type: str, payload: dict[str, Any]) -> int:
    # The outbox is platform state: a business user triggers the event, but the
    # row itself is written with system rights so ACLs never block a workflow.
    system = Env(env.db, registry=env.registry, su=True)
    return system["platform.outbox_event"].create(
        {"event_type": event_type, "payload": json.dumps(payload, default=str)}
    )


class Worker:
    """Drains the outbox and runs due cron jobs. Safe to run as N processes."""

    def __init__(self, db, registry, *, batch_size: int = 100):
        self.db = db
        self.registry = registry
        self.batch_size = batch_size
        self.env = Env(db, registry=registry, su=True)

    # -- outbox ------------------------------------------------------------
    def process_outbox(self) -> dict[str, int]:
        stats = {"processed": 0, "retried": 0, "failed": 0}
        events = self.env["platform.outbox_event"]
        with self.db.cursor() as cur:
            # A worker that died mid-handler leaves rows in "processing"; return
            # them to the queue once they are clearly stale.
            cur.execute(
                """
                UPDATE platform.outbox_event
                   SET state = 'pending'
                 WHERE state = 'processing'
                   AND write_date < now() - interval '15 minutes'
                """
            )
            # Claim atomically: the row lock is released with this statement, but
            # the state change means no other worker can pick the same event up.
            cur.execute(
                """
                WITH claimed AS (
                    SELECT id
                      FROM platform.outbox_event
                     WHERE state = 'pending' AND attempts < max_attempts
                     ORDER BY id
                     LIMIT %s
                     FOR UPDATE SKIP LOCKED
                )
                UPDATE platform.outbox_event AS event
                   SET state = 'processing',
                       attempts = event.attempts + 1,
                       write_date = now()
                  FROM claimed
                 WHERE event.id = claimed.id
                RETURNING event.id
                """,
                (self.batch_size,),
            )
            ids = [row[0] for row in cur.fetchall()]
        for event_id in ids:
            row = events.read([event_id])[0]
            event_type = row["event_type"]
            try:
                payload = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            try:
                subscribers = handlers_for(event_type)
                if not subscribers:
                    raise LookupError(f"no handler registered for {event_type!r}")
                for handler in subscribers:
                    handler(self.env, payload)
            except Exception as exc:  # noqa: BLE001 - handlers fail in arbitrary ways
                attempts = row["attempts"] or 0
                state = "failed" if attempts >= (row["max_attempts"] or 5) else "pending"
                events.write(
                    [event_id],
                    {
                        "state": state,
                        "error": "".join(
                            traceback.format_exception_only(type(exc), exc)
                        ).strip()[:2000],
                        "processed_at": None,
                    },
                )
                stats["failed" if state == "failed" else "retried"] += 1
                log.warning("event %s failed (attempt %s): %s", event_type, attempts, exc)
            else:
                events.write(
                    [event_id],
                    {
                        "state": "processed",
                        "processed_at": dt.datetime.now(dt.UTC),
                        "error": None,
                    },
                )
                # Fan the delivered event out to connected clients. This is a
                # notification, not part of the outbox transaction: a bus
                # failure must never turn a delivered event into a retry.
                try:
                    Bus(self.db, self.registry).publish(
                        "platform", event_type, {**payload, "outbox_id": event_id}
                    )
                except Exception:
                    log.exception("bus publish failed for event %s", event_id)
                stats["processed"] += 1
        return stats

    # -- cron --------------------------------------------------------------
    def run_due_crons(self) -> int:
        now = dt.datetime.now(dt.UTC)
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM core.ir_cron
                 WHERE active AND (next_call IS NULL OR next_call <= %s)
                 ORDER BY next_call NULLS FIRST, id
                 LIMIT %s
                 FOR UPDATE SKIP LOCKED
                """,
                (now, 10),
            )
            ids = [row[0] for row in cur.fetchall()]
        crons = self.env["core.ir_cron"]
        ran = 0
        for cron_id in ids:
            row = crons.read([cron_id])[0]
            path = row["code"]
            ok = True
            try:
                module_name, _, function_name = path.rpartition(".")
                module = importlib.import_module(module_name)
                getattr(module, function_name)(self.env)
            except Exception:
                ok = False
                log.exception("cron %s failed", path)
            interval = max(int(row.get("interval_minutes") or 60), 1)
            crons.write(
                [cron_id],
                {
                    "last_call": now,
                    "next_call": now + dt.timedelta(minutes=interval if ok else 1),
                },
            )
            ran += 1
        return ran

    def once(self) -> dict[str, Any]:
        stats = self.process_outbox()
        stats["crons"] = self.run_due_crons()
        return stats
