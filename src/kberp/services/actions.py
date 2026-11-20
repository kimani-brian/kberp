"""Object buttons: a small registry of named transitions per model.

Views name a button; the controller looks up the handler here. Keeping the
registry separate from the web layer means the same transition can be called
from a form POST, a JSON-RPC call or a job without duplicating checks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..orm.model import ConflictError, ValidationError

Handler = Callable[..., dict[str, Any]]

_HANDLERS: dict[tuple[str, str], Handler] = {}


def object_action(model_name: str, name: str):
    def decorate(handler: Handler) -> Handler:
        _HANDLERS[(model_name, name)] = handler
        return handler

    return decorate


def available(model_name: str) -> list[str]:
    return sorted(name for model, name in _HANDLERS if model == model_name)


def invoke(env, model_name: str, name: str, record_id: int, **kwargs: Any) -> dict[str, Any]:
    handler = _HANDLERS.get((model_name, name))
    if handler is None:
        raise ValidationError(f"unknown action {name!r} for {model_name}")
    if model_name not in env.registry.models:
        raise ValidationError(f"unknown model {model_name}")
    with env.db.transaction():
        result = handler(env, record_id, **kwargs)
    return result or {"ok": True}


__all__ = ["ConflictError", "Handler", "available", "invoke", "object_action"]
