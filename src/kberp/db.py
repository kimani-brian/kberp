"""PostgreSQL access: one pool per process, explicit transactions."""

from __future__ import annotations

import contextlib
import contextvars
import time
from collections.abc import Iterator, Sequence
from typing import Any, Self

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool

from .config import Settings

# Schema ownership, declared in one place (architecture.md §11.1).
SCHEMAS = (
    "core",
    "contacts",
    "sales",
    "purchase",
    "inventory",
    "accounting",
    "chatter",
    "platform",
)


def ident(name: str) -> sql.Identifier:
    """Quote an SQL identifier. Never interpolate identifiers by hand."""
    return sql.Identifier(name)


# A connection bound for the duration of a request or job. Every ORM call inside
# the `transaction()` block shares it, so a multi-step document flow commits or
# rolls back as one unit. Outside a block each call keeps its own transaction.
_bound_connection: contextvars.ContextVar[psycopg.Connection | None] = (
    contextvars.ContextVar("kberp_bound_connection", default=None)
)


class Database:
    def __init__(self, settings: Settings, *, min_size: int = 1, max_size: int = 10):
        self.settings = settings
        self._pool = ConnectionPool(
            settings.conninfo(),
            min_size=min_size,
            max_size=max_size,
            timeout=10,
            kwargs={"application_name": "kberp"},
            open=False,
        )

    # -- lifecycle ---------------------------------------------------------
    def open(self, wait: float = 30.0) -> None:
        deadline = time.monotonic() + wait
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._pool.open(wait=True, timeout=5)
                return
            except Exception as exc:  # noqa: BLE001 - retry any start-up failure
                last = exc
                time.sleep(0.5)
        raise RuntimeError(f"cannot connect to PostgreSQL: {last}")

    def close(self) -> None:
        self._pool.close()

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- units of work -----------------------------------------------------
    @contextlib.contextmanager
    def cursor(self) -> Iterator[psycopg.Cursor]:
        """A transaction boundary, or a cursor on the bound transaction."""
        bound = _bound_connection.get()
        if bound is not None:
            with bound.cursor() as cur:
                yield cur
            return
        with self._pool.connection() as conn, conn.cursor() as cur:
            yield cur

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Group every ORM call in this context into one transaction.

        Nesting is allowed: an inner block joins the outer one and leaves the
        commit to it. Services never call this; the request or job boundary owns
        the transaction.
        """
        if _bound_connection.get() is not None:
            yield
            return
        with self._pool.connection() as conn:
            token = _bound_connection.set(conn)
            try:
                yield
            except BaseException:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise
            finally:
                _bound_connection.reset(token)

    def fetch_all(self, query: Any, params: Sequence[Any] | None = None) -> list[tuple]:
        with self.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def fetch_one(self, query: Any, params: Sequence[Any] | None = None) -> tuple | None:
        rows = self.fetch_all(query, params)
        return rows[0] if rows else None

    def execute(self, query: Any, params: Sequence[Any] | None = None) -> int:
        with self.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount

    # -- schema helpers ----------------------------------------------------
    def ensure_schemas(self) -> None:
        with self.cursor() as cur:
            for schema in SCHEMAS:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident(schema)))

    def table_exists(self, schema: str, table: str) -> bool:
        row = self.fetch_one(
            """
            SELECT 1 FROM information_schema.tables
             WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        return row is not None

    def columns(self, schema: str, table: str) -> list[str]:
        rows = self.fetch_all(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
             ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return [r[0] for r in rows]
