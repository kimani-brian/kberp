"""Settings, resolved from the environment with development defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_host: str = "localhost"
    db_port: int = 5433
    db_user: str = "kberp"
    db_password: str = "kberp"
    db_name: str = "kberp"

    host: str = "0.0.0.0"
    port: int = 8069
    secret_key: str = "dev-secret"
    debug: bool = True

    admin_login: str = "admin"
    admin_password: str = "admin"

    addons_path: Path = BASE_DIR / "addons"
    mail_dir: Path = BASE_DIR.parents[1] / "var" / "mail"

    session_cookie: str = "kberp_sid"
    session_ttl: int = 60 * 60 * 12

    # Optional: when unset the bus still works through database polling and
    # the WebSocket loop; Redis only shortens fan-out latency across workers.
    redis_url: str = ""

    # Optional bearer token for /metrics. In production the endpoint is closed
    # unless this is set; in development it is open for convenience.
    metrics_token: str = ""

    # Short hash of the source baked into the container, shown in the top bar so
    # a stale container cannot masquerade as the current build.
    build_id: str = "dev"

    @classmethod
    def from_env(cls) -> Settings:
        addons = Path(_env("KB_ADDONS_PATH", str(BASE_DIR / "addons")))
        build_id = _env("KB_BUILD_ID", "")
        if not build_id:
            for candidate in (BASE_DIR.parents[1] / "BUILD_ID", Path("/app/BUILD_ID")):
                if candidate.is_file():
                    build_id = candidate.read_text(encoding="utf-8").strip()
                    break
        return cls(
            db_host=_env("KB_DB_HOST", "localhost"),
            db_port=_env_int("KB_DB_PORT", 5433),
            db_user=_env("KB_DB_USER", "kberp"),
            db_password=_env("KB_DB_PASSWORD", "kberp"),
            db_name=_env("KB_DB_NAME", "kberp"),
            host=_env("KB_HOST", "0.0.0.0"),
            port=_env_int("KB_PORT", 8069),
            secret_key=_env("KB_SECRET_KEY", "dev-secret"),
            debug=_env_bool("KB_DEBUG", True),
            admin_login=_env("KB_ADMIN_LOGIN", "admin"),
            admin_password=_env("KB_ADMIN_PASSWORD", "admin"),
            addons_path=addons,
            mail_dir=Path(_env("KB_MAIL_DIR", str(BASE_DIR.parents[1] / "var" / "mail"))),
            redis_url=_env("KB_REDIS_URL", ""),
            metrics_token=_env("KB_METRICS_TOKEN", ""),
            build_id=build_id or "dev",
        )

    def conninfo(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password}"
        )
