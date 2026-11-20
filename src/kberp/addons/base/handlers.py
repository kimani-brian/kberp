"""Base event handlers, registered at import time.

P0 ships one handler so the outbox roundtrip is demonstrable end to end. Later
phases register their own handlers in `<module>/handlers/events.py`.
"""

from __future__ import annotations

import logging

from ...services.events import register_handler

log = logging.getLogger(__name__)


def on_ping(env, payload):
    """A platform heartbeat, used by the P0 demo and the smoke test."""
    env["core.ir_module"].search_count([])  # proves the handler has DB access
    log.info("platform.ping received: %s", payload)


def heartbeat(env):
    """Scheduled liveness probe, seeded as a cron job on install."""
    env["core.ir_module"].search_count([])
    log.info("scheduled heartbeat")


def prune_bus(env):
    """Retention sweep for the replay buffer (scheduled on install)."""
    from ...services.bus import Bus

    return Bus(env.db, env.registry).prune(older_than_minutes=24 * 60)


register_handler("platform.ping", on_ping)
