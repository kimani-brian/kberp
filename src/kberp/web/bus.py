"""WebSocket and polling delivery for `platform.bus_message`.

The browser uses `/web/bus` twice: as a WebSocket when the server supports it
(Werkzeug threaded dev server, Gunicorn with a WebSocket-capable worker), and as
a plain poll every few seconds when it does not. Both read the same durable
rows, so a dropped connection only delays a message, it never loses one.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any
from urllib.parse import urlsplit

from werkzeug.exceptions import BadRequest
from werkzeug.wrappers import Request, Response

from ..orm.model import AccessError
from ..services.bus import Bus, subscriber, wake

log = logging.getLogger(__name__)


def _json(payload: dict[str, Any], status: int = 200) -> Response:
    return Response(json.dumps(payload, default=str), status=status, mimetype="application/json")


def channels_for(state: dict[str, Any], raw: str | None) -> list[str]:
    user = state["user"]
    user_id = user["id"]
    allowed = {"platform", f"user.{user_id}"}
    allowed.update(f"group.{g}" for g in user.get("group_xmlids") or [])
    requested = [ch.strip() for ch in (raw or "").split(",") if ch.strip()]
    if not requested:
        requested = ["platform", f"user.{user_id}"]
    result: list[str] = []
    for channel in requested:
        if channel in allowed:
            result.append(channel)
        elif channel.startswith("record."):
            # P0 has no record rules yet. Any internal user may follow a record
            # channel; the ACL gate lands with the first business documents.
            result.append(channel)
        else:
            raise AccessError(f"cannot subscribe to channel {channel!r}")
    if not result:
        raise AccessError("no bus channels selected")
    return result


def _check_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    if parsed.netloc and parsed.netloc != request.host:
        raise AccessError("cross-origin bus connections are not allowed")


def poll(app, request: Request) -> Response:
    state = app._require_state(request)
    _check_origin(request)
    channels = channels_for(state, request.args.get("channels"))
    try:
        after = int(request.args.get("after") or 0)
    except ValueError as exc:
        raise BadRequest("after must be an integer") from exc
    bus = Bus(app.db, app.registry, app.settings)
    messages = bus.messages_after(channels, after)
    latest = max([after, *[m["id"] for m in messages]])
    return _json(
        {
            "type": "poll",
            "channels": channels,
            "latest": latest,
            "messages": messages,
        }
    )


def websocket(app, request: Request) -> Response | None:
    """Accept a WebSocket and stream bus envelopes until the client leaves.

    Returns ``None`` because the handshake has already been written to the raw
    socket; the WSGI caller must return an empty iterable.
    """
    from simple_websocket import ConnectionClosed, Server

    state = app._require_state(request)
    _check_origin(request)
    channels = channels_for(state, request.args.get("channels"))
    bus = Bus(app.db, app.registry, app.settings)

    try:
        ws = Server.accept(request.environ, ping_interval=20)
    except Exception as exc:  # noqa: BLE001 - malformed upgrade request
        log.warning("websocket handshake failed: %s", exc)
        return Response("WebSocket upgrade failed", status=400, mimetype="text/plain")

    after_arg = request.args.get("after")
    last = bus.latest_id(channels) if after_arg is None else int(after_arg)
    try:
        ws.send(
            json.dumps(
                {"type": "hello", "channels": channels, "latest": last},
                default=str,
            )
        )
    except ConnectionClosed:
        return None

    pubsub = subscriber(bus)
    try:
        while True:
            if pubsub is None:
                incoming = ws.receive(timeout=0.75)
            else:
                wake(pubsub, 0.75)
                incoming = ws.receive(timeout=0)
            if incoming:
                _handle_client_message(ws, incoming, last)
            messages = bus.messages_after(channels, last, limit=100)
            for message in messages:
                ws.send(json.dumps({"type": "bus", **message}, default=str))
                last = max(last, message["id"])
    except ConnectionClosed:
        pass
    except Exception:
        log.exception("bus websocket failed")
        with contextlib.suppress(Exception):
            ws.send(json.dumps({"type": "error", "message": "bus connection failed"}))
    finally:
        if pubsub is not None:
            with contextlib.suppress(Exception):
                pubsub.close()
        with contextlib.suppress(Exception):
            ws.close()
    return None


def _handle_client_message(ws, incoming: str | bytes, last: int) -> None:
    try:
        payload = json.loads(incoming)
    except (TypeError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    if payload.get("type") == "ping":
        ws.send(json.dumps({"type": "pong", "latest": last}))
