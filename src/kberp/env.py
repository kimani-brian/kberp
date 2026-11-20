"""Request/job environment: database, user, registry and access decisions."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .orm.model import AccessError, BaseModel

MODE_COLUMNS = {"read": 0, "write": 1, "create": 2, "unlink": 3}


class Env:
    def __init__(
        self,
        db,
        *,
        registry=None,
        uid: int | None = None,
        user: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        su: bool = False,
    ):
        self.db = db
        self.registry = registry
        self.uid = uid if uid is not None else (user or {}).get("id")
        self.user = user
        self.context = context or {}
        self.su = su
        self._acl_cache: dict[tuple[str, str], bool] = {}
        self._rule_cache: dict[tuple[str, str], list[Any] | None] = {}

    # -- model access ------------------------------------------------------
    def __getitem__(self, model_name: str) -> BaseModel:
        if self.registry is None:
            raise RuntimeError("environment has no registry")
        try:
            model = self.registry.models[model_name]
        except KeyError:
            raise KeyError(f"unknown model {model_name!r}") from None
        return model(self)

    def __contains__(self, model_name: str) -> bool:
        return self.registry is not None and model_name in self.registry.models

    # -- access control ----------------------------------------------------
    def check_access(self, model_name: str, mode: str) -> None:
        if self.su:
            return
        if self.user and self.user.get("is_admin"):
            return
        column = MODE_COLUMNS.get(mode)
        if column is None:
            raise ValueError(f"unknown access mode {mode!r}")
        key = (model_name, mode)
        allowed = self._acl_cache.get(key)
        if allowed is None:
            allowed = self._load_acl(model_name, column)
            self._acl_cache[key] = allowed
        if not allowed:
            who = (self.user or {}).get("login", "anonymous")
            raise AccessError(f"{who} cannot {mode} {model_name}")

    def _load_acl(self, model_name: str, column: int) -> bool:
        groups: Iterable[str] = (self.user or {}).get("group_xmlids") or []
        query = """
            SELECT perm_read, perm_write, perm_create, perm_unlink
              FROM core.ir_model_access
             WHERE model = %s AND group_xmlid = ANY(%s)
        """
        try:
            rows = self.db.fetch_all(query, (model_name, list(groups)))
        except Exception:  # noqa: BLE001 - metadata may not exist during bootstrap
            # Metadata table not created yet (bootstrap/install): deny by default.
            return False
        return any(bool(row[column]) for row in rows)

    # -- helpers -----------------------------------------------------------
    def rule_domain(self, model_name: str, mode: str) -> list[Any] | None:
        """The row filter a signed-in user must satisfy for `mode`.

        `None` means every row is allowed. Global rules are combined with AND;
        rules that belong to groups are combined with OR, matching how Odoo
        unions group rules. The result is a prefix domain ready for the compiler.
        """
        if self.su or self.is_admin:
            return None
        key = (model_name, mode)
        if key in self._rule_cache:
            return self._rule_cache[key]
        domain = self._load_rules(model_name, mode)
        self._rule_cache[key] = domain
        return domain

    def _load_rules(self, model_name: str, mode: str) -> list[Any] | None:
        column = MODE_COLUMNS.get(mode)
        if column is None:
            return None
        query = """
            SELECT domain, group_xmlid, is_global,
                   perm_read, perm_write, perm_create, perm_unlink
              FROM core.ir_rule
             WHERE model = %s
        """
        try:
            rows = self.db.fetch_all(query, (model_name,))
        except Exception:  # noqa: BLE001 - metadata may not exist during bootstrap
            return None
        groups = set((self.user or {}).get("group_xmlids") or [])
        global_domains: list[list[Any]] = []
        group_domains: list[list[Any]] = []
        for row in rows:
            domain_text, group_xmlid, is_global, *perms = row
            if not perms[column]:
                continue
            if group_xmlid and group_xmlid not in groups:
                continue
            parsed = self._substitute_company(json.loads(domain_text or "[]"))
            if not parsed:
                continue
            if is_global or not group_xmlid:
                global_domains.append(parsed)
            else:
                group_domains.append(parsed)
        combined = list(global_domains)
        if group_domains:
            combined.append(_or_domains(group_domains))
        return _and_domains(combined) or None

    def _substitute_company(self, domain: Any) -> Any:
        company_id = (self.user or {}).get("company_id")

        def walk(value: Any) -> Any:
            if isinstance(value, (list, tuple)):
                if len(value) == 3 and value[2] == "$company":
                    name, operator = value[0], value[1]
                    if operator in ("in", "not in"):
                        return [name, operator, [company_id] if company_id else []]
                    return [name, operator, company_id]
                return [walk(item) for item in value]
            return value

        return walk(domain)

    def with_context(self, **context: Any) -> Env:
        merged = {**self.context, **context}
        return Env(
            self.db,
            registry=self.registry,
            uid=self.uid,
            user=self.user,
            context=merged,
            su=self.su,
        )

    @property
    def is_admin(self) -> bool:
        return bool(self.user and self.user.get("is_admin"))


def _and_domains(domains: list[list[Any]]) -> list[Any]:
    combined: list[Any] = []
    for domain in domains:
        if not domain:
            continue
        combined = list(domain) if not combined else ["&", *combined, *domain]
    return combined


def _or_domains(domains: list[list[Any]]) -> list[Any]:
    if not domains:
        return []
    if len(domains) == 1:
        return list(domains[0])
    return ["|"] * (len(domains) - 1) + [token for domain in domains for token in domain]
