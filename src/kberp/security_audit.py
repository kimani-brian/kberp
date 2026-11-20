"""Security posture audit used by F1 and by CI.

The audit is deliberately evidence-oriented: it reports what is missing and
fails only on findings that are unsafe in any deployment. Broader observations
(models writable by internal users, for example) are returned as warnings so a
reviewer can decide whether the permission is intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .env import Env

DEFAULT_SECRETS = {"dev-secret", "change-me-in-production", "secret"}
DEFAULT_PASSWORDS = {"admin", "password", "changeme", "kberp"}


class SecurityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def _models(env: Env) -> list[str]:
    return sorted(name for name in env.registry.models if name not in {"core.ir_module"})


def missing_access(env: Env) -> list[str]:
    """Return registered models that no access rule mentions."""
    governed = {
        row["model"]
        for row in env["core.ir_model_access"].read(env["core.ir_model_access"].search([]))
    }
    return [name for name in _models(env) if name not in governed]


def internal_write_models(env: Env) -> list[str]:
    """Models an ordinary internal user may create, change or delete.

    These are not necessarily wrong; the list exists so an auditor can review
    the write surface rather than discover it by probing.
    """
    rows = env["core.ir_model_access"].read(
        env["core.ir_model_access"].search([("group_xmlid", "=", "base.group_user")])
    )
    writable = {
        row["model"]
        for row in rows
        if row.get("perm_write") or row.get("perm_create") or row.get("perm_unlink")
    }
    return sorted(writable)


def production_settings_findings(settings: Settings) -> list[Finding]:
    """Configuration that is acceptable in development and unsafe in production."""
    if settings.debug:
        return []
    findings: list[Finding] = []
    if settings.secret_key in DEFAULT_SECRETS or len(settings.secret_key) < 32:
        findings.append(
            Finding(
                "high",
                "secret-key",
                "KB_SECRET_KEY is a development default or shorter than 32 characters",
            )
        )
    if settings.admin_password in DEFAULT_PASSWORDS or len(settings.admin_password) < 12:
        findings.append(
            Finding(
                "high",
                "admin-password",
                "KB_ADMIN_PASSWORD is a well-known default or shorter than 12 characters",
            )
        )
    if settings.db_password in DEFAULT_PASSWORDS:
        findings.append(
            Finding("high", "db-password", "KB_DB_PASSWORD is a well-known default")
        )
    return findings


def audit(env: Env, settings: Settings) -> dict[str, Any]:
    """Build the full security report used by the CLI and the F1 evidence."""
    findings: list[Finding] = []
    for model in missing_access(env):
        findings.append(
            Finding("high", "missing-acl", f"{model} has no access rule")
        )
    findings.extend(production_settings_findings(settings))

    access_count = env["core.ir_model_access"].search_count([])
    rule_count = env["core.ir_rule"].search_count([])
    group_count = env["core.res_groups"].search_count([])
    return {
        "ok": not any(item.severity == "high" for item in findings),
        "models": len(_models(env)),
        "access_rules": access_count,
        "record_rules": rule_count,
        "groups": group_count,
        "internal_write_models": internal_write_models(env),
        "findings": [item.as_dict() for item in findings],
        "notes": [
            "Record rules are enforced server-side by Env and never by the UI.",
            "CSRF, session cookies and password hashing are covered by tests/test_web.py.",
        ],
    }


def check_security(env: Env, settings: Settings) -> dict[str, Any]:
    report = audit(env, settings)
    high = [item for item in report["findings"] if item["severity"] == "high"]
    if high:
        detail = "\n  ".join(f"{item['code']}: {item['message']}" for item in high)
        raise SecurityError("security audit failed:\n  " + detail)
    return report
