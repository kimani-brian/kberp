"""Session storage and authentication helpers.

Sessions live in `platform.session` (database-backed), so a restart never logs
users out and multiple web processes share state.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from ..db import Database
from ..env import Env
from ..registry import Registry
from ..security import hash_password, new_csrf_token, new_session_token, verify_password

SESSION_TABLE = "platform.session"


class Auth:
    def __init__(self, db: Database, registry: Registry, ttl: int = 60 * 60 * 12):
        self.db = db
        self.registry = registry
        self.ttl = ttl

    def _env(self) -> Env:
        return Env(self.db, registry=self.registry, su=True)

    # -- authentication ----------------------------------------------------
    def authenticate(self, login: str, password: str) -> dict[str, Any] | None:
        env = self._env()
        ids = env["core.user"].search([("login", "=", login.strip())], limit=1)
        if not ids:
            # Equalise timing between unknown user and wrong password.
            verify_password(None, password)
            return None
        rows = env["core.user"].read(ids)
        if not rows:
            return None
        user = rows[0]
        if not user.get("active", True):
            return None
        if not verify_password(user.get("password_hash"), password):
            return None
        return self._payload(user)

    def _payload(self, user: dict[str, Any]) -> dict[str, Any]:
        company = user.get("company_id")
        return {
            "id": user["id"],
            "login": user["login"],
            "name": user["name"],
            "is_admin": bool(user.get("is_admin")),
            "group_xmlids": user.get("group_xmlids") or [],
            "company_id": company.get("id") if isinstance(company, dict) else company,
        }

    # -- sessions ----------------------------------------------------------
    def start_session(self, user_id: int) -> dict[str, str]:
        token = new_session_token()
        csrf = new_csrf_token()
        expires = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=self.ttl)
        env = self._env()
        env["platform.session"].create(
            {"token": token, "user_id": user_id, "csrf": csrf, "expires_at": expires}
        )
        return {"token": token, "csrf": csrf, "expires": expires.isoformat()}

    def load_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        env = self._env()
        sessions = env["platform.session"]
        ids = sessions.search([("token", "=", token)], limit=1)
        if not ids:
            return None
        session = sessions.read(ids)[0]
        expires = session.get("expires_at")
        if expires is None or expires <= dt.datetime.now(dt.UTC):
            sessions.unlink(ids)
            return None
        user_id = session["user_id"]
        if isinstance(user_id, dict):
            user_id = user_id.get("id")
        user_ids = env["core.user"].search([("id", "=", user_id)], limit=1)
        if not user_ids:
            return None
        rows = env["core.user"].read(user_ids)
        if not rows or not rows[0].get("active", True):
            return None
        user = self._payload(rows[0])
        return {"token": token, "csrf": session["csrf"], "user": user}

    def end_session(self, token: str | None) -> None:
        if not token:
            return
        env = self._env()
        ids = env["platform.session"].search([("token", "=", token)])
        if ids:
            env["platform.session"].unlink(ids)

    def refresh_csrf(self, token: str) -> str:
        csrf = new_csrf_token()
        env = self._env()
        ids = env["platform.session"].search([("token", "=", token)], limit=1)
        if ids:
            env["platform.session"].write(ids, {"csrf": csrf})
        return csrf

    # -- flash messages (queued per session, survive one redirect) ---------
    def add_flash(self, token: str, message: str, level: str = "success") -> None:
        env = self._env()
        sessions = env["platform.session"]
        ids = sessions.search([("token", "=", token)], limit=1)
        if not ids:
            return
        current = json.loads(sessions.read(ids)[0].get("flash") or "[]")
        current.append({"level": level, "message": message})
        sessions.write(ids, {"flash": json.dumps(current[-5:])})

    def take_flash(self, token: str) -> list[dict[str, str]]:
        env = self._env()
        sessions = env["platform.session"]
        ids = sessions.search([("token", "=", token)], limit=1)
        if not ids:
            return []
        messages = json.loads(sessions.read(ids)[0].get("flash") or "[]")
        if messages:
            sessions.write(ids, {"flash": "[]"})
        return messages

    # -- user management (P0: used by tests and the CLI) -------------------
    def create_user(
        self,
        login: str,
        password: str,
        name: str,
        groups: list[str],
        *,
        is_admin: bool = False,
        company_id: int | None = None,
    ) -> int:
        env = self._env()
        if company_id is None:
            companies = env["core.company"].search([], limit=1)
            company_id = companies[0] if companies else None
        return env["core.user"].create(
            {
                "name": name,
                "login": login,
                "password_hash": hash_password(password),
                "is_admin": is_admin,
                "group_xmlids": groups,
                "company_id": company_id,
            }
        )
