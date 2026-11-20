"""Scheduled accounting jobs."""

from __future__ import annotations


def run_followups(env) -> int:
    from ..services.closing import send_due_followups

    return send_due_followups(env)
