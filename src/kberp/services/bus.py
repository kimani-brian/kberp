"""Realtime bus: durable messages in PostgreSQL, optional Redis fan-out.

PostgreSQL is the source of truth. Every message is a `platform.bus_message`
row, so a client that reconnects can replay what it missed with `after=<id>`.
Redis, when configured, is only a latency optimisation: `publish()` also emits
a notification on the `kberp:bus` channel and WebSocket loops wake on it
instead of waiting for their next database poll.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from typing import Any

from ..env import Env

log = logging.getLogger(__name__)

REDIS_CHANNEL = "kberp:bus"
_CLIENTS: dict[str, Any] = {}
_CLIENTS_LOCK = threading.Lock()


def parse_payload(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {"value": value}


class Bus:
    def __init__(self, db, registry, settings=None):
        self.db = db
        self.registry = registry
        self.settings = settings
        self.env = Env(db, registry=registry, su=True)

    # -- publishing --------------------------------------------------------
    def publish(self, channel: str, event: str, payload: dict[str, Any] | None = None) -> int:
        body = json.dumps(payload or {}, default=str)
        message_id = self.env["platform.bus_message"].create(
            {"channel": channel, "event": event, "payload": body}
        )
        self._notify({"id": message_id, "channel": channel, "event": event})
        return message_id

    def _notify(self, envelope: dict[str, Any]) -> None:
        client = self.redis_client()
        if client is None:
            return
        try:
            client.publish(REDIS_CHANNEL, json.dumps(envelope, default=str))
        except Exception as exc:  # noqa: BLE001 - Redis is optional
            log.debug("redis publish failed: %s", exc)

    # -- reading -----------------------------------------------------------
    def messages_after(
        self, channels: list[str], after_id: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        if not channels:
            return []
        model = self.env["platform.bus_message"]
        ids = model.search(
            [("channel", "in", channels), ("id", ">", int(after_id))],
            order="id",
            limit=max(1, min(int(limit), 500)),
        )
        rows = model.read(ids)
        return [self._envelope(row) for row in rows]

    def latest_id(self, channels: list[str]) -> int:
        if not channels:
            return 0
        ids = self.env["platform.bus_message"].search(
            [("channel", "in", channels)], order="-id", limit=1
        )
        return int(ids[0]) if ids else 0

    @staticmethod
    def _envelope(row: dict[str, Any]) -> dict[str, Any]:
        created = row.get("create_date")
        return {
            "id": row["id"],
            "channel": row["channel"],
            "event": row["event"],
            "payload": parse_payload(row.get("payload")),
            "create_date": created.isoformat() if isinstance(created, dt.datetime) else created,
        }

    # -- retention ---------------------------------------------------------
    def prune(self, older_than_minutes: int = 24 * 60) -> int:
        """Delete delivered messages. The bus is a replay buffer, not an archive."""
        return self.db.execute(
            """
            DELETE FROM platform.bus_message
             WHERE create_date < now() - (%s * interval '1 minute')
            """,
            (max(1, int(older_than_minutes)),),
        )

    # -- infrastructure ----------------------------------------------------
    def redis_client(self):
        if self.settings is None or not getattr(self.settings, "redis_url", ""):
            return None
        url = self.settings.redis_url
        with _CLIENTS_LOCK:
            client = _CLIENTS.get(url)
            if client is not None:
                return client
            try:
                import redis

                client = redis.Redis.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
                client.ping()
            except Exception as exc:  # noqa: BLE001 - degrade to database polling
                log.warning("redis unavailable at %s: %s", url, exc)
                return None
            _CLIENTS[url] = client
            return client

    def ready(self) -> tuple[bool, str]:
        """Readiness probe: DB is the caller's job; this reports Redis."""
        if self.settings is None or not getattr(self.settings, "redis_url", ""):
            return True, "disabled"
        client = self.redis_client()
        if client is None:
            return False, "unreachable"
        try:
            client.ping()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        return True, "ok"


def subscriber(bus: Bus):
    """A Redis pub/sub subscription, or None when Redis is not configured.

    The caller still polls PostgreSQL; the subscription only decides when to
    wake up. Keeping it optional means one code path works in every deployment.
    """
    client = bus.redis_client()
    if client is None:
        return None
    try:
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(REDIS_CHANNEL)
        return pubsub
    except Exception as exc:  # noqa: BLE001
        log.warning("redis subscribe failed: %s", exc)
        return None


def wake(pubsub, timeout: float = 1.0) -> None:
    """Block until a notification or timeout. Never raises into the socket loop."""
    if pubsub is None:
        return
    try:
        pubsub.get_message(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log.debug("redis get_message failed: %s", exc)
