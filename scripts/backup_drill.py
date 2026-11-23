#!/usr/bin/env python
"""Backup/restore drill for NFR-008 (RPO <= 15 min, RTO <= 4 h).

Run against a quiet staging copy, never against production:

    .venv/bin/python scripts/backup_drill.py

The drill makes a custom-format ``pg_dump`` of the configured database,
restores it into a separate database, compares every table's row count and a
sample checksum with the source, then boots the app against the restored copy
and checks parity. It also reads ``pg_stat_archiver`` to verify WAL archiving,
which is what bounds point-in-time loss to the archive interval.

``--keep`` leaves the dump and the restored database in place for inspection.
Without it, both are removed at the end of the run.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from kberp.config import Settings
from kberp.db import Database
from kberp.env import Env
from kberp.parity import parity_report
from kberp.registry import Registry

RPO_SECONDS = 15 * 60
RTO_SECONDS = 4 * 60 * 60
SAMPLED_ROWS = 200


def connect(settings: Settings, dbname: str, *, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=dbname,
        user=settings.db_user,
        password=settings.db_password,
        autocommit=autocommit,
    )


def table_names(conn: psycopg.Connection) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name
              FROM information_schema.tables
             WHERE table_type = 'BASE TABLE'
               AND table_schema NOT IN ('pg_catalog', 'information_schema')
             ORDER BY table_schema, table_name
            """
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def fingerprint(conn: psycopg.Connection) -> dict[str, tuple[int, str]]:
    """Row count plus a deterministic sample hash for every application table."""
    result: dict[str, tuple[int, str]] = {}
    with conn.cursor() as cur:
        for schema, name in table_names(conn):
            relation = sql.Identifier(schema, name)
            cur.execute(
                sql.SQL(
                    "SELECT count(*), md5(coalesce(string_agg(x::text, '|'), '')) "
                    "FROM (SELECT * FROM {} ORDER BY 1 LIMIT {}) x"
                ).format(relation, sql.Literal(SAMPLED_ROWS))
            )
            count, digest = cur.fetchone()
            result[f"{schema}.{name}"] = (int(count), str(digest))
    return result


def _pg_client(command: str, settings: Settings, *args: str) -> None:
    env = {**os.environ, "PGPASSWORD": settings.db_password}
    cmd = [
        command,
        "-h",
        settings.db_host,
        "-p",
        str(settings.db_port),
        "-U",
        settings.db_user,
        *args,
    ]
    subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)


def _recreate_target(settings: Settings, target: str) -> None:
    with (
        connect(settings, "postgres", autocommit=True) as admin,
        admin.cursor() as cur,
    ):
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(target)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))


def force_archive(settings: Settings) -> None:
    """Reset archiver counters and switch WAL so the evidence is from this drill."""
    with connect(settings, settings.db_name, autocommit=True) as admin, admin.cursor() as cur:
        cur.execute("SELECT pg_stat_reset_shared('archiver')")
        cur.execute("SELECT pg_switch_wal()")


def wal_evidence(conn: psycopg.Connection) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, setting FROM pg_settings
             WHERE name IN ('archive_mode', 'archive_command', 'archive_timeout')
            """
        )
        config = {row[0]: row[1] for row in cur.fetchall()}
        cur.execute(
            """
            SELECT archived_count, last_archived_wal, last_archived_time,
                   failed_count, last_failed_time
              FROM pg_stat_archiver
            """
        )
        row = cur.fetchone()
    archived, last_wal, last_time, failed, last_failed = row
    timeout = int(config.get("archive_timeout", "0") or 0)
    return {
        "archive_mode": config.get("archive_mode", "off"),
        "archive_command": config.get("archive_command", "(disabled)"),
        "archive_timeout": timeout,
        "archived_count": int(archived or 0),
        "failed_count": int(failed or 0),
        "last_wal": last_wal,
        "last_time": last_time,
        "last_failed": last_failed,
        "met": (
            config.get("archive_mode") == "on"
            and 0 < timeout <= RPO_SECONDS
            and int(failed or 0) == 0
            and last_time is not None
        ),
    }


def smoke_test(settings: Settings, target: str) -> None:
    """The restored copy must boot the app and pass the parity scorecard."""
    target_settings = dataclasses.replace(settings, db_name=target)
    db = Database(target_settings)
    db.open()
    try:
        registry = Registry(target_settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        assert env["core.partner"].search([], limit=1), "no partners in restored database"
        report = parity_report(env)
        assert report["ok"], report["problems"]
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="kberp_restore_drill", help="restore database name")
    parser.add_argument("--keep", action="store_true", help="keep the dump and restored database")
    args = parser.parse_args()

    settings = Settings.from_env()
    source = settings.db_name
    target = args.target
    if target == source:
        print("--target must differ from the source database", file=sys.stderr)
        return 2

    temp_dir: Path | None = None
    dump_path: Path | None = None
    created = False
    problems: list[str] = []
    try:
        with connect(settings, source) as source_conn:
            force_archive(settings)

            temp_dir = Path(tempfile.mkdtemp(prefix="kberp-drill-"))
            dump_path = temp_dir / f"{source}.dump"
            dump_started = time.perf_counter()
            _pg_client(
                "pg_dump",
                settings,
                "-Fc",
                "--no-owner",
                "--no-privileges",
                "-d",
                source,
                "-f",
                str(dump_path),
            )
            dump_seconds = time.perf_counter() - dump_started
            source_fp = fingerprint(source_conn)

            # A checkpoint on a busy source can hold a WAL segment back for a
            # while. Read the evidence after the dump, then wait past the
            # one-minute archive_timeout before calling RPO unmet.
            wal = wal_evidence(source_conn)
            for _ in range(180):
                if wal["last_time"] is not None or wal["failed_count"]:
                    break
                time.sleep(0.5)
                wal = wal_evidence(source_conn)
            if not wal["met"]:
                problems.append("WAL archiving does not yet bound RPO to 15 minutes")

        print(f"source : {source}")
        print(f"dump   : {dump_path.name} ({dump_path.stat().st_size:,} bytes, {dump_seconds:.1f}s)")
        print(f"target : {target}")

        started = time.perf_counter()
        _recreate_target(settings, target)
        created = True
        _pg_client(
            "pg_restore",
            settings,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "-d",
            target,
            str(dump_path),
        )
        with connect(settings, target) as restored:
            target_fp = fingerprint(restored)
        smoke_test(settings, target)
        restore_seconds = time.perf_counter() - started

        mismatches = []
        for name in sorted(source_fp.keys() | target_fp.keys()):
            if source_fp.get(name) != target_fp.get(name):
                mismatches.append(f"{name}: {source_fp.get(name)} != {target_fp.get(name)}")
        if mismatches:
            problems.append(f"{len(mismatches)} table(s) differ after restore")
            for line in mismatches[:10]:
                print(f"  MISMATCH {line}", file=sys.stderr)

        rto_met = restore_seconds <= RTO_SECONDS
        if not rto_met:
            problems.append(f"restore exceeded RTO ({restore_seconds:.1f}s)")
        print(f"tables : {len(source_fp)} compared, {len(mismatches)} mismatches")
        print(
            f"RPO    : {'MET' if wal['met'] else 'NOT MET'} "
            f"(archive_mode={wal['archive_mode']}, archive_timeout={wal['archive_timeout']}s, "
            f"last WAL {wal['last_wal']} at {wal['last_time']}, failures={wal['failed_count']})"
        )
        print(
            f"RTO    : {'MET' if rto_met else 'NOT MET'} "
            f"({restore_seconds:.1f}s to restore, compare and smoke-test; budget {RTO_SECONDS}s)"
        )
        if problems:
            for problem in problems:
                print(f"FAIL: {problem}", file=sys.stderr)
            return 1
        print("drill passed")
        return 0
    finally:
        if created and not args.keep:
            with (
                connect(settings, "postgres", autocommit=True) as admin,
                admin.cursor() as cur,
            ):
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(target)
                    )
                )
        if temp_dir is not None and not args.keep:
            shutil.rmtree(temp_dir, ignore_errors=True)
        elif args.keep:
            print(f"kept dump at {dump_path}", file=sys.stderr)
            print(f"kept restored database {target}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
