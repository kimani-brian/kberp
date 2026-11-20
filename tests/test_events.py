"""Outbox and scheduler tests: delivery, retry and dead-letter."""

from __future__ import annotations

import datetime as dt
import json
import uuid

from kberp.services.events import Worker, emit


def _event(env, event_id):
    return env["platform.outbox_event"].read([event_id])[0]


def test_ping_is_emitted_and_processed(env, db, registry):
    event_id = emit(env, "platform.ping", {"hello": "world"})
    row = _event(env, event_id)
    assert row["state"] == "pending"
    assert json.loads(row["payload"]) == {"hello": "world"}

    stats = Worker(db, registry).once()
    assert stats["processed"] >= 1
    row = _event(env, event_id)
    assert row["state"] == "processed"
    assert row["attempts"] == 1
    assert row["processed_at"] is not None
    assert not row["error"]


def test_handler_can_write(env, db, registry):
    from kberp.services.events import register_handler

    marker = f"Marker {uuid.uuid4().hex[:8]}"

    def handler(worker_env, payload):
        worker_env["core.product_category"].create({"name": marker})

    register_handler("test.write_category", handler)
    emit(env, "test.write_category", {})
    Worker(db, registry).once()
    assert env["core.product_category"].search_count([("name", "=", marker)]) == 1


def test_failure_is_retried_then_dead_lettered(env, db, registry):
    event_id = env["platform.outbox_event"].create(
        {
            "event_type": f"test.unhandled_{uuid.uuid4().hex[:6]}",
            "payload": "{}",
            "max_attempts": 2,
        }
    )
    worker = Worker(db, registry)

    first = worker.once()
    assert first["retried"] >= 1
    row = _event(env, event_id)
    assert row["state"] == "pending"
    assert row["attempts"] == 1
    assert "no handler" in row["error"]

    second = worker.once()
    assert second["failed"] >= 1
    row = _event(env, event_id)
    assert row["state"] == "failed"
    assert row["attempts"] == 2
    assert "no handler" in row["error"]

    # Dead-lettered rows are not claimed again.
    third = worker.process_outbox()
    assert third == {"processed": 0, "retried": 0, "failed": 0}


def test_cron_runs_and_reschedules(env, db, registry):
    cron_id = env["core.ir_cron"].search(
        [("code", "=", "kberp.addons.base.handlers.heartbeat")], limit=1
    )[0]

    Worker(db, registry).once()
    row = env["core.ir_cron"].read([cron_id])[0]
    assert row["last_call"] is not None
    assert row["next_call"] is not None
    assert row["next_call"] > dt.datetime.now(dt.UTC)
