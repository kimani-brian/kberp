"""Command line entry point: init, seed, run, worker, emit."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

from .config import Settings
from .db import Database
from .env import Env
from .installer import Installer
from .migration import KINDS, import_file, write_templates
from .parity import ParityError, check_menus, check_parity, check_views
from .registry import Registry
from .security_audit import SecurityError, check_security
from .services.events import Worker, emit
from .web.app import create_app


def _settings() -> Settings:
    return Settings.from_env()


def cmd_init(args: argparse.Namespace) -> int:
    installer = Installer(_settings())
    summary = installer.init(demo=args.with_demo, fresh=args.fresh)
    print("KB ERP initialised")
    print(f"  modules : {', '.join(summary['modules'])}")
    print(f"  models  : {summary['models']}")
    print(f"  apps    : {', '.join(summary['apps'])}")
    print(f"  admin   : {_settings().admin_login} (id {summary['admin_id']})")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    settings = _settings()
    installer = Installer(settings)
    summary = installer.init(demo=True)
    print(f"demo data ready (models: {summary['models']})")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from werkzeug.serving import run_simple

    settings = _settings()
    app = create_app(settings)
    app.db.open()
    print(f"KB ERP on http://{args.host}:{args.port}")
    run_simple(
        args.host,
        args.port,
        app,
        use_reloader=args.reload,
        use_debugger=settings.debug,
        threaded=True,
    )
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = _settings()
    db = Database(settings)
    db.open()
    registry = Registry(settings)
    registry.load()
    worker = Worker(db, registry)

    if args.once:
        print(json.dumps(worker.once(), indent=2))
        db.close()
        return 0

    stopping = {"flag": False}

    def stop(*_args):
        stopping["flag"] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("worker started")
    while not stopping["flag"]:
        stats = worker.once()
        if any(stats.values()):
            print(json.dumps(stats))
        time.sleep(args.interval)
    db.close()
    print("worker stopped")
    return 0


def cmd_emit(args: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings)
    db.open()
    try:
        registry = Registry(settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        try:
            payload = json.loads(args.payload or "{}")
        except json.JSONDecodeError as exc:
            print(f"invalid JSON payload: {exc}", file=sys.stderr)
            return 2
        event_id = emit(env, args.event_type, payload)
        print(f"emitted {args.event_type} as event {event_id}")
    finally:
        db.close()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings)
    db.open()
    try:
        registry = Registry(settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        checks = (
            ["menus", "views", "parity", "security"] if args.what == "all" else [args.what]
        )
        try:
            for what in checks:
                if what == "menus":
                    check_menus(env)
                elif what == "views":
                    check_views(env)
                elif what == "parity":
                    report = check_parity(env)
                    print(
                        "parity: menus {menus[score]}% ({menus[total]}/{menus[expected]}), "
                        "actions {actions[score]}% ({actions[total]}/{actions[expected]}), "
                        "{n} apps, settings groups: {groups}".format(
                            n=len(report["apps"]),
                            groups=", ".join(report["settings_groups"]),
                            **report,
                        )
                    )
                elif what == "security":
                    report = check_security(env, settings)
                    print(
                        "security: {models} models, {access_rules} ACLs, "
                        "{record_rules} rules, {groups} groups, "
                        "{total_findings} findings, {write} internal-write models".format(
                            total_findings=len(report["findings"]),
                            write=len(report["internal_write_models"]),
                            **report,
                        )
                    )
        except (ParityError, SecurityError) as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"checks passed: {', '.join(checks)}")
        return 0
    finally:
        db.close()


def cmd_import(args: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings)
    db.open()
    try:
        registry = Registry(settings)
        registry.load()
        env = Env(db, registry=registry, su=True)
        with db.transaction():
            result = import_file(
                env,
                args.kind,
                Path(args.file),
                dry_run=not args.commit,
                validate=args.validate,
            )
        print(json.dumps(result.as_dict(), indent=2))
        if not result.ok:
            return 1
        verb = "validated" if result.dry_run else "imported"
        print(
            f"{verb} {result.rows} row(s): {result.created} created, "
            f"{result.updated} updated, {result.skipped} skipped",
            file=sys.stderr,
        )
        return 0
    finally:
        db.close()


def cmd_templates(args: argparse.Namespace) -> int:
    paths = write_templates(Path(args.dir) if args.dir else None)
    for path in paths:
        print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kberp", description="KB ERP")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create schemas, load XML metadata and reference data")
    init.add_argument("--with-demo", action="store_true", help="load demo partners and products")
    init.add_argument("--fresh", action="store_true", help="drop the KB ERP schemas first")
    init.set_defaults(func=cmd_init)

    seed = sub.add_parser("seed", help="load demo data into an existing database")
    seed.set_defaults(func=cmd_seed)

    run = sub.add_parser("run", help="start the development web server")
    run.add_argument("--host", default=None)
    run.add_argument("--port", type=int, default=None)
    run.add_argument("--reload", action="store_true")
    run.set_defaults(func=cmd_run)

    worker = sub.add_parser("worker", help="drain the outbox and run due cron jobs")
    worker.add_argument("--once", action="store_true", help="run one pass and exit")
    worker.add_argument("--interval", type=float, default=2.0)
    worker.set_defaults(func=cmd_worker)

    emit_cmd = sub.add_parser("emit", help="enqueue an outbox event")
    emit_cmd.add_argument("event_type")
    emit_cmd.add_argument("--payload", default="{}")
    emit_cmd.set_defaults(func=cmd_emit)

    check = sub.add_parser("check", help="run metadata, parity and security checks")
    check.add_argument(
        "what",
        nargs="?",
        choices=["menus", "views", "parity", "security", "all"],
        default="all",
    )
    check.set_defaults(func=cmd_check)

    import_cmd = sub.add_parser("import", help="dry-run or commit a CSV migration file")
    import_cmd.add_argument("kind", choices=list(KINDS))
    import_cmd.add_argument("--file", required=True, help="CSV file to import")
    import_cmd.add_argument(
        "--commit", action="store_true", help="write changes (default is a dry run)"
    )
    import_cmd.add_argument(
        "--validate",
        action="store_true",
        help="validate imported stock counts immediately",
    )
    import_cmd.set_defaults(func=cmd_import)

    templates = sub.add_parser("import-templates", help="write the CSV import templates")
    templates.add_argument("--dir", default=None, help="target directory")
    templates.set_defaults(func=cmd_templates)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        settings = _settings()
        args.host = args.host or settings.host
        args.port = args.port or settings.port
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
