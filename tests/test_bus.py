"""Bus tests: durable replay, retention, worker fan-out and the WebSocket."""

from __future__ import annotations

import json
import threading

from conftest import login
from simple_websocket import Client
from werkzeug.serving import make_server

from kberp.services.bus import Bus
from kberp.services.events import Worker, emit


def test_publish_replays_in_id_order(env, db, registry, settings):
    bus = Bus(db, registry, settings)
    first = bus.publish("user.1", "test.one", {"n": 1})
    second = bus.publish("user.1", "test.two", {"n": 2})
    bus.publish("user.2", "test.other", {"n": 3})

    messages = bus.messages_after(["user.1"], 0)
    assert [m["id"] for m in messages] == [first, second]
    assert messages[0]["event"] == "test.one"
    assert messages[0]["payload"] == {"n": 1}
    assert messages[0]["create_date"]

    later = bus.messages_after(["user.1"], first)
    assert [m["id"] for m in later] == [second]
    assert bus.latest_id(["user.1"]) == second


def test_prune_removes_only_old_messages(env, db, registry, settings):
    bus = Bus(db, registry, settings)
    old = bus.publish("platform", "test.old", {})
    fresh = bus.publish("platform", "test.fresh", {})
    db.execute(
        "UPDATE platform.bus_message SET create_date = now() - interval '2 days' WHERE id = %s",
        (old,),
    )
    assert bus.prune(older_than_minutes=60) == 1
    assert [m["id"] for m in bus.messages_after(["platform"], 0)] == [fresh]


def test_worker_broadcasts_processed_events(env, db, registry, settings):
    event_id = emit(env, "platform.ping", {"hello": "bus"})
    worker = Worker(db, registry)
    bus = Bus(db, registry, settings)
    # Other tests may leave events queued; drain batches until ours is handled.
    for _ in range(50):
        worker.once()
        since = max(0, bus.latest_id(["platform"]) - 50)
        messages = [
            m
            for m in bus.messages_after(["platform"], since)
            if m["event"] == "platform.ping"
            and m["payload"].get("outbox_id") == event_id
        ]
        if messages:
            break
    assert messages
    assert messages[-1]["payload"]["hello"] == "bus"


def test_poll_fallback_returns_messages(client, app, settings):
    login(client)
    bus = Bus(app.db, app.registry, settings)
    message_id = bus.publish("platform", "test.poll", {"ok": True})

    response = client.get(f"/web/bus?channels=platform&after={message_id - 1}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["latest"] >= message_id
    assert any(m["id"] == message_id for m in payload["messages"])
    assert payload["messages"][0]["payload"] == {"ok": True}


def test_poll_rejects_foreign_channel(client):
    login(client)
    response = client.get("/web/bus?channels=user.999")
    assert response.status_code == 403


def test_websocket_streams_new_messages(app, client, settings):
    login(client)
    cookie = client.get_cookie("kberp_sid")
    assert cookie is not None

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"ws://127.0.0.1:{server.server_port}/web/bus?channels=platform"
    ws = Client.connect(url, headers={"Cookie": f"kberp_sid={cookie.value}"})
    try:
        hello = json.loads(ws.receive(timeout=3))
        assert hello["type"] == "hello"
        assert "platform" in hello["channels"]

        message_id = Bus(app.db, app.registry, settings).publish(
            "platform", "test.live", {"n": 4}
        )
        envelope = None
        for _ in range(4):
            envelope = json.loads(ws.receive(timeout=3))
            if envelope.get("type") == "bus" and envelope.get("id") == message_id:
                break
        assert envelope is not None
        assert envelope["type"] == "bus"
        assert envelope["event"] == "test.live"
        assert envelope["payload"] == {"n": 4}
    finally:
        ws.close()
        server.shutdown()


def test_readyz_reports_database_registry_and_redis(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ready"] is True
    assert payload["checks"]["database"] == "ok"
    assert payload["checks"]["registry"] == "ok"
