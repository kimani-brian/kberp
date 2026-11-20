"""Werkzeug application: launcher, app shell, views and JSON-RPC."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import mimetypes
import socket
import time
import uuid
from pathlib import Path
from typing import Any

import psycopg
from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.routing import Map, Rule
from werkzeug.utils import redirect
from werkzeug.wrappers import Request, Response

from ..config import Settings
from ..db import Database
from ..env import Env
from ..metrics import Metrics
from ..orm.domains import DomainError
from ..orm.model import AccessError, ConflictError, ValidationError
from ..registry import Registry
from ..security import constant_time_equals, new_csrf_token
from ..services import actions as object_actions
from . import bus as web_bus
from . import views
from .auth import Auth

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"

PAGE_SIZE = 40
GROUP_LIMIT = 12
GROUP_PAGE_SIZE = 12

log = logging.getLogger("kberp.web")

# Smart buttons shown on a contact. A button appears only when its model
# exists, so nothing points at a screen a later phase has not shipped yet.
SMART_BUTTONS: tuple[tuple[str, str, str | None, list[Any]], ...] = (
    ("addresses", "Addresses", None, []),
    ("bank_accounts", "Bank Accounts", "core.bank_account", []),
    ("sales", "Sales", "sales.order", []),
    ("purchases", "Purchases", "purchase.order", []),
    (
        "invoiced",
        "Invoiced",
        "accounting.move",
        [("move_type", "in", ["out_invoice", "out_refund"])],
    ),
    (
        "vendor_bills",
        "Vendor Bills",
        "accounting.move",
        [("move_type", "in", ["in_invoice", "in_refund"])],
    ),
    ("lots", "Lots/Serials", "inventory.lot", []),
)

# Which delivery phase brings each app's business menus (see phases.md).
PHASE_HINT = {
    "contacts": "C1 - Contact directory core",
    "sales": "S1 - Quotations and sales orders are live",
    "accounting": "A1 - Ledger core, taxes and posting are live",
    "purchase": "P1 - RFQ core and receipt request",
    "inventory": "I2 - Counts, scrap, lots and traceability are live",
}


class Application:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings)
        self.registry = Registry(settings)
        self.registry.load()
        self.auth = Auth(self.db, self.registry, settings.session_ttl)
        self.metrics = Metrics()
        self.templates = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            autoescape=select_autoescape(["html"]),
        )
        self.templates.filters["fmt"] = self._template_format
        self.templates.globals["app_color"] = self.app_color
        self.url_map = Map(
            [
                Rule("/", endpoint="root"),
                Rule("/health", endpoint="health"),
                Rule("/healthz", endpoint="healthz"),
                Rule("/readyz", endpoint="readyz"),
                Rule("/metrics", endpoint="metrics"),
                Rule("/web/login", endpoint="login", methods=["GET", "POST"]),
                Rule("/web/logout", endpoint="logout", methods=["POST"]),
                Rule("/apps", endpoint="launcher"),
                Rule("/settings", endpoint="settings"),
                Rule("/apps/<app_key>", endpoint="app_home"),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>",
                    endpoint="list_view",
                    methods=["GET"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/new",
                    endpoint="form_new",
                    methods=["GET", "POST"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>",
                    endpoint="form_edit",
                    methods=["GET", "POST"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>/delete",
                    endpoint="delete_record",
                    methods=["POST"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>/button/<name>",
                    endpoint="object_button",
                    methods=["POST"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>/report/<name>",
                    endpoint="object_report",
                    methods=["GET"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>/note",
                    endpoint="chatter_note",
                    methods=["POST"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>/follow",
                    endpoint="chatter_follow",
                    methods=["POST"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>/activity",
                    endpoint="chatter_activity",
                    methods=["POST"],
                ),
                Rule(
                    "/apps/<app_key>/action/<int:action_id>/<int:record_id>/activity"
                    "/<int:activity_id>/done",
                    endpoint="chatter_activity_done",
                    methods=["POST"],
                ),
                Rule("/web/rpc", endpoint="rpc", methods=["POST"]),
                Rule("/web/bus", endpoint="bus", methods=["GET", "POST"]),
                Rule("/web/bus", endpoint="bus_ws", websocket=True),
                Rule("/favicon.ico", endpoint="favicon"),
                Rule("/static/<path:filename>", endpoint="static"),
            ]
        )

    # -- WSGI --------------------------------------------------------------
    def __call__(self, environ, start_response):
        request = Request(environ)
        request_id = (request.headers.get("X-Request-ID") or uuid.uuid4().hex)[:64]
        environ["kberp.request_id"] = request_id
        started = time.perf_counter()
        endpoint = "unknown"
        self.metrics.start()
        try:
            try:
                self._attach_session(request)
                adapter = self.url_map.bind_to_environ(environ)
                endpoint, values = adapter.match()
                handler = getattr(self, f"on_{endpoint}")
                if endpoint not in {
                    "root",
                    "login",
                    "static",
                    "health",
                    "healthz",
                    "readyz",
                    "metrics",
                    "logout",
                    "rpc",
                    "favicon",
                }:
                    redirect_response = self._require_login(request)
                    if redirect_response is not None:
                        response = redirect_response
                    else:
                        response = handler(request, **values)
                else:
                    response = handler(request, **values)
            except HTTPException as exc:
                response = self._http_error(request, exc)
            except Exception as exc:  # noqa: BLE001 - last-resort guard
                response = self._error_response(request, exc)
            elapsed = time.perf_counter() - started
            if response is None:
                # A WebSocket handler owns the raw socket. Hang up before the WSGI
                # envelope finishes, otherwise Werkzeug writes HTTP headers after
                # the WebSocket frames. The write then fails as a dropped
                # connection, which the server handles without a response.
                self.metrics.finish(request.method, endpoint, 101, elapsed)
                start_response(
                    "200 OK",
                    [("Content-Type", "text/plain"), ("Content-Length", "0")],
                )
                raw = environ.get("werkzeug.socket")
                if raw is not None:
                    with contextlib.suppress(OSError):
                        raw.shutdown(socket.SHUT_RDWR)
                return []
            response.headers["X-Request-ID"] = request_id
            self.metrics.finish(request.method, endpoint, response.status_code, elapsed)
            log.info(
                "%s %s %s %.1fms request_id=%s",
                request.method,
                request.path,
                response.status_code,
                elapsed * 1000,
                request_id,
            )
            return response(environ, start_response)
        except BaseException:
            self.metrics.finish(request.method, endpoint, 500, time.perf_counter() - started)
            raise

    def _attach_session(self, request: Request) -> None:
        token = request.cookies.get(self.settings.session_cookie)
        request.environ["kberp.session"] = self.auth.load_session(token) if token else None

    # -- helpers -----------------------------------------------------------
    def _state(self, request: Request) -> dict[str, Any] | None:
        return request.environ.get("kberp.session")

    def _require_state(self, request: Request) -> dict[str, Any]:
        state = self._state(request)
        if state is None:
            raise AccessError("authentication required")
        return state

    def _env(self, request: Request, *, su: bool = False) -> Env:
        state = self._state(request)
        user = state["user"] if state else None
        return Env(
            self.db,
            registry=self.registry,
            uid=user["id"] if user else None,
            user=user,
            su=su,
        )

    def _require_login(self, request: Request) -> Response | None:
        if self._state(request) is None:
            return redirect(f"/web/login?next={request.path}")
        return None

    def _check_csrf(self, request: Request) -> None:
        state = self._state(request)
        if state is None:
            raise AccessError("no session")
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not constant_time_equals(token or "", state["csrf"]):
            raise AccessError("invalid CSRF token")

    def _context(self, request: Request, **extra: Any) -> dict[str, Any]:
        state = self._state(request)
        user = state["user"] if state else None
        flash = self.auth.take_flash(state["token"]) if state else []
        context: dict[str, Any] = {
            "user": user,
            "is_admin": bool(user and user.get("is_admin")),
            "apps": self._apps(user),
            "csrf_token": state["csrf"] if state else "",
            "flash": flash,
            "menus": [],
            "current_app": None,
            "settings_url": "/settings" if user and user.get("is_admin") else None,
            "title": "KB ERP",
        }
        context.update(extra)
        return context

    def _render(self, template: str, context: dict[str, Any], status: int = 200) -> Response:
        html = self.templates.get_template(template).render(**context)
        return Response(html, status=status, mimetype="text/html")

    def _env_csrf(self) -> str:
        return new_csrf_token()

    # -- metadata ----------------------------------------------------------
    def app_color(self, key: str) -> str:
        return {
            "contacts": "#0E7C86",
            "sales": "#4F46E5",
            "accounting": "#1E8E5A",
            "purchase": "#B45309",
            "inventory": "#1D4ED8",
            "settings": "#5C6672",
        }.get(key, "#3D5AFE")

    def _app_name(self, app_key: str) -> str:
        manifest = self._app_manifest(app_key)
        return manifest.label if manifest else app_key

    def _apps(self, user: dict[str, Any] | None) -> list[dict[str, Any]]:
        apps = []
        for manifest in self.registry.apps():
            apps.append(
                {
                    "key": manifest.icon,
                    "name": manifest.label,
                    "sequence": manifest.sequence,
                    "summary": manifest.summary,
                    "phase": PHASE_HINT.get(manifest.icon, ""),
                }
            )
        return apps

    def _app_manifest(self, app_key: str):
        for manifest in self.registry.apps():
            if manifest.icon == app_key:
                return manifest
        return None

    def _visible(self, groups: str | None, user: dict[str, Any] | None) -> bool:
        if not groups:
            return True
        if user is None:
            return False
        if user.get("is_admin"):
            return True
        allowed = {g.strip() for g in groups.split(",") if g.strip()}
        return bool(allowed & set(user.get("group_xmlids") or []))

    def _menu_rows(self, env: Env, user: dict[str, Any] | None) -> list[dict[str, Any]]:
        menus = env["core.ir_ui_menu"]
        ids = menus.search([], order="sequence, id")
        return menus.read(ids)

    def _app_root_menu(self, env: Env, app_key: str) -> dict[str, Any] | None:
        for row in self._menu_rows(env, None):
            if row.get("is_app") and row.get("web_icon") == app_key:
                return row
        return None

    def _menu_tree(
        self,
        env: Env,
        parent_id: int | None,
        user: dict[str, Any] | None,
        app_key: str,
    ) -> list[dict[str, Any]]:
        domain = [] if parent_id is None else [("parent_id", "=", parent_id)]
        menus = env["core.ir_ui_menu"]
        ids = menus.search(domain, order="sequence, id")
        tree = []
        for row in menus.read(ids):
            if not self._visible(row.get("groups"), user):
                continue
            node = {
                "id": row["id"],
                "name": row["name"],
                "action_type": row.get("action_type"),
                "action_id": row.get("action_id"),
                "children": self._menu_tree(env, row["id"], user, app_key),
                "url": None,
            }
            node["url"] = self._menu_url(app_key, node)
            tree.append(node)
        return tree

    def _menu_url(self, app_key: str, node: dict[str, Any]) -> str | None:
        if node["action_type"] == "window" and node["action_id"]:
            return f"/apps/{app_key}/action/{node['action_id']}?menu={node['id']}"
        if node["action_type"] == "client" and node["action_id"]:
            return f"/apps/{app_key}?menu={node['id']}"
        return None

    def menu_url(self, app_key: str, node: dict[str, Any]) -> str | None:
        return self._menu_url(app_key, node)

    def _breadcrumbs(
        self, env: Env, app_key: str, menu_id: int | None, action_name: str
    ) -> list[dict[str, Any]]:
        crumbs: list[dict[str, Any]] = [
            {"name": self._app_name(app_key), "url": f"/apps/{app_key}"}
        ]
        if menu_id:
            rows = {r["id"]: r for r in self._menu_rows(env, None)}
            chain = []
            cursor: int | None = menu_id
            while cursor in rows:
                row = rows[cursor]
                chain.append(row)
                parent = row.get("parent_id")
                cursor = parent.get("id") if isinstance(parent, dict) else (parent or 0)
            for row in reversed(chain):
                crumbs.append({"name": row["name"], "url": None})
        if action_name:
            crumbs.append({"name": action_name, "url": None})
        return crumbs

    def _resolve_action(self, env: Env, action_id: int) -> dict[str, Any]:
        actions = env["core.ir_act_window"]
        rows = actions.read([action_id])
        if not rows:
            raise NotFound("action not found")
        return rows[0]

    def _resolve_view(self, env: Env, model: str, view_type: str) -> dict[str, Any] | None:
        ids = env["core.ir_ui_view"].search(
            [("model", "=", model), ("type", "=", view_type)], order="priority, id", limit=1
        )
        if not ids:
            return None
        return env["core.ir_ui_view"].read(ids)[0]

    # -- routes: auth ------------------------------------------------------
    def on_root(self, request: Request) -> Response:
        if self._state(request) is None:
            return redirect("/web/login")
        return redirect("/apps")

    def on_health(self, request: Request) -> Response:
        try:
            self.db.fetch_one("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - report any health failure
            return Response(f"unhealthy: {exc}", status=503, mimetype="text/plain")
        return Response("ok", mimetype="text/plain")

    def on_healthz(self, request: Request) -> Response:
        return self.on_health(request)

    def on_readyz(self, request: Request) -> Response:
        checks: dict[str, str] = {}
        ready = True
        try:
            self.db.fetch_one("SELECT 1")
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"unavailable: {exc}"
            ready = False
        checks["registry"] = "ok" if self.registry.models else "empty"
        ready = ready and bool(self.registry.models)
        redis_ok, redis_detail = web_bus.Bus(self.db, self.registry, self.settings).ready()
        checks["redis"] = redis_detail
        ready = ready and redis_ok
        return Response(
            json.dumps({"ready": ready, "checks": checks}),
            status=200 if ready else 503,
            mimetype="application/json",
        )

    def on_metrics(self, request: Request) -> Response:
        token = self.settings.metrics_token
        if token:
            supplied = request.headers.get("Authorization", "")
            if not constant_time_equals(supplied, f"Bearer {token}"):
                return Response("forbidden", status=403, mimetype="text/plain")
        elif not self.settings.debug:
            return Response("metrics disabled", status=403, mimetype="text/plain")

        gauges: dict[str, float] = {"kberp_models": float(len(self.registry.models))}
        try:
            counts = self.db.fetch_one(
                "SELECT count(*) FILTER (WHERE state = 'pending'), "
                "count(*) FILTER (WHERE state = 'failed') FROM platform.outbox_event"
            )
            pending, failed = counts if counts else (0, 0)
            gauges["kberp_outbox_pending_events"] = float(pending or 0)
            gauges["kberp_outbox_failed_events"] = float(failed or 0)
            gauges["kberp_database_up"] = 1.0
        except Exception:  # noqa: BLE001 - a scrape must never fail on a gauge
            gauges["kberp_database_up"] = 0.0
        return Response(
            self.metrics.render(gauges),
            mimetype="text/plain; version=0.0.4; charset=utf-8",
        )

    def on_bus(self, request: Request) -> Response:
        return web_bus.poll(self, request)

    def on_bus_ws(self, request: Request) -> Response | None:
        return web_bus.websocket(self, request)

    def on_login(self, request: Request) -> Response:
        if self._state(request) is not None:
            return redirect("/apps")
        error = None
        if request.method == "POST":
            cookie_token = request.cookies.get("kberp_csrf") or ""
            form_token = request.form.get("csrf_token") or ""
            if not (cookie_token and form_token) or not constant_time_equals(
                cookie_token, form_token
            ):
                error = "Your session expired. Please try again."
            else:
                user = self.auth.authenticate(
                    request.form.get("login", ""), request.form.get("password", "")
                )
                if user is None:
                    error = "Wrong login or password."
                else:
                    session = self.auth.start_session(user["id"])
                    target = request.args.get("next") or "/apps"
                    if not target.startswith("/") or target.startswith("//"):
                        target = "/apps"
                    response = redirect(target)
                    response.set_cookie(
                        self.settings.session_cookie,
                        session["token"],
                        httponly=True,
                        samesite="Lax",
                        secure=not self.settings.debug,
                        max_age=self.settings.session_ttl,
                    )
                    return response
        csrf = new_csrf_token()
        response = self._render(
            "login.html",
            {"csrf_token": csrf, "error": error, "title": "Sign in - KB ERP", "apps": []},
        )
        response.set_cookie("kberp_csrf", csrf, httponly=True, samesite="Lax")
        return response

    def on_logout(self, request: Request) -> Response:
        state = self._state(request)
        if state:
            self._check_csrf(request)
            self.auth.end_session(state["token"])
        response = redirect("/web/login")
        response.delete_cookie(self.settings.session_cookie)
        return response

    # -- routes: shell -----------------------------------------------------
    def on_launcher(self, request: Request) -> Response:
        return self._render(
            "launcher.html",
            self._context(request, title="Apps - KB ERP"),
        )

    def on_app_home(self, request: Request, app_key: str) -> Response:
        manifest = self._app_manifest(app_key)
        if manifest is None:
            raise NotFound("app not found")
        env = self._env(request)
        root = self._app_root_menu(env, app_key)
        menu_id = request.args.get("menu", type=int)
        menus = (
            self._menu_tree(env, root["id"], self._require_state(request)["user"], app_key)
            if root
            else []
        )
        return self._render(
            "app_home.html",
            self._context(
                request,
                title=f"{manifest.label} - KB ERP",
                current_app={"key": app_key, "name": manifest.label},
                menus=menus,
                app=manifest,
                phase=PHASE_HINT.get(app_key, ""),
                dashboard=(
                    self._accounting_dashboard(env)
                    if app_key == "accounting"
                    else self._inventory_dashboard(env)
                    if app_key == "inventory"
                    else None
                ),
                dashboard_title=(
                    "Ledger at a glance"
                    if app_key == "accounting"
                    else "Stock at a glance"
                    if app_key == "inventory"
                    else ""
                ),
                menu_id=menu_id,
                breadcrumbs=[{"name": manifest.label, "url": None}],
            ),
        )

    def _accounting_dashboard(self, env: Env) -> dict[str, Any]:
        from ..addons.accounting.services.posting import balances

        totals = balances(env)
        revenue = -totals.get("income", 0)
        expenses = totals.get("expense", 0)
        def money(value) -> str:
            return f"{value:,.2f}"
        kpis = [
            {"label": "Revenue", "value": money(revenue)},
            {"label": "Expenses", "value": money(expenses)},
            {"label": "Profit", "value": money(revenue - expenses)},
            {"label": "Cash and bank", "value": money(totals.get("bank", 0))},
            {
                "label": "Draft entries",
                "value": str(env["accounting.move"].search_count([("state", "=", "draft")])),
            },
            {
                "label": "Posted entries",
                "value": str(env["accounting.move"].search_count([("state", "=", "posted")])),
            },
        ]
        return {"kpis": kpis}

    def _inventory_dashboard(self, env: Env) -> dict[str, Any]:
        pickings = env["inventory.picking"]
        to_receive = pickings.search_count(
            [("picking_type", "=", "in"), ("state", "in", ["draft", "assigned"])]
        )
        to_deliver = pickings.search_count(
            [("picking_type", "=", "out"), ("state", "in", ["draft", "assigned"])]
        )
        late = pickings.search_count(
            [
                ("scheduled_date", "<", dt.date.today()),
                ("state", "in", ["draft", "assigned"]),
            ]
        )
        value = 0.0
        for quant in env["inventory.quant"].read(env["inventory.quant"].search([])):
            product = quant.get("product_id") or {}
            product_id = product.get("id") if isinstance(product, dict) else product
            if not product_id:
                continue
            row = env["core.product_template"].read([int(product_id)])
            if row:
                value += float(quant["qty"]) * float(row[0].get("standard_price") or 0)
        return {
            "kpis": [
                {"label": "To receive", "value": str(to_receive)},
                {"label": "To deliver", "value": str(to_deliver)},
                {"label": "Late transfers", "value": str(late)},
                {"label": "Stock value", "value": f"{value:,.2f}"},
            ]
        }

    def on_settings(self, request: Request) -> Response:
        state = self._require_state(request)
        if not state["user"].get("is_admin"):
            raise AccessError("settings are restricted")
        env = self._env(request)
        root = None
        for row in self._menu_rows(env, None):
            if row["xml_id"] == "base.menu_settings_root":
                root = row
        if root is None:
            raise NotFound("settings menu missing")
        menus = self._menu_tree(env, root["id"], state["user"], "settings")
        return self._render(
            "app_home.html",
            self._context(
                request,
                title="Settings - KB ERP",
                current_app={"key": "settings", "name": "Settings"},
                menus=menus,
                app=None,
                phase="P0 - Platform, shell and launcher",
                menu_id=None,
                breadcrumbs=[{"name": "Settings", "url": None}],
                is_settings=True,
            ),
        )

    # -- routes: list ------------------------------------------------------
    def on_list_view(self, request: Request, app_key: str, action_id: int) -> Response:
        env = self._env(request)
        state = self._require_state(request)
        data = self._list_payload(
            env,
            app_key,
            action_id,
            q=request.args.get("q") or "",
            filter_name=request.args.get("filter") or "",
            offset=request.args.get("offset", type=int, default=0) or 0,
            menu_id=request.args.get("menu", type=int),
            view=request.args.get("view") or "",
            group_by=request.args.get("group_by") or "",
        )
        context = self._context(
            request,
            title=f"{data['action']['name']} - KB ERP",
            current_app={"key": app_key, "name": self._app_name(app_key)},
            menus=self._app_menus(env, app_key, state["user"]),
            **data,
        )
        return self._render("list.html", context)

    def _list_payload(
        self,
        env: Env,
        app_key: str,
        action_id: int,
        *,
        q: str = "",
        filter_name: str = "",
        offset: int = 0,
        menu_id: int | None = None,
        view: str = "",
        group_by: str = "",
    ) -> dict[str, Any]:
        action = self._resolve_action(env, action_id)
        model_name = action["res_model"]
        model = env[model_name]
        view_row = self._resolve_view(env, model_name, "list")
        if view_row is None:
            raise NotFound(f"no list view for {model_name}")
        spec = views.list_spec(model, views.parse_arch(view_row["arch"]))
        kanban_row = self._resolve_view(env, model_name, "kanban")
        kanban = (
            views.kanban_spec(model, views.parse_arch(kanban_row["arch"]))
            if kanban_row
            else None
        )
        selected_view = "kanban" if view == "kanban" and kanban else "list"

        search_row = self._resolve_view(env, model_name, "search")
        search = (
            views.search_spec(model, views.parse_arch(search_row["arch"]))
            if search_row
            else {"search_fields": [], "filters": [], "group_bys": []}
        )

        q = (q or "").strip()
        selected = filter_name or ""
        group_names = {group["name"] for group in search["group_bys"]}
        selected_group = group_by if group_by in group_names else ""
        domain = views.parse_domain(action.get("domain"))
        if q:
            domain = domain + self._text_domain(search["search_fields"], q)
        for flt in search["filters"]:
            if flt["name"] == selected:
                domain = domain + flt["domain"]

        offset = max(int(offset or 0), 0)
        total = model.search_count(domain)
        groups: list[dict[str, Any]] = []
        if selected_group:
            groups = model.read_group(domain, selected_group, limit=GROUP_LIMIT)
            for group in groups:
                group_domain = [*domain, (selected_group, "=", group["value"])]
                group_ids = model.search(
                    group_domain, order=model._order, limit=GROUP_PAGE_SIZE
                )
                group["records"] = self._decorate_records(
                    env, model_name, model.read(group_ids)
                )
            records: list[dict[str, Any]] = []
        else:
            ids = model.search(domain, order=model._order, limit=PAGE_SIZE, offset=offset)
            records = self._decorate_records(env, model_name, model.read(ids))
        can_create = self._can(env, model_name, "create") and spec["can_create"]
        can_delete = self._can(env, model_name, "unlink") and spec["can_delete"]
        base_url = f"/apps/{app_key}/action/{action_id}"
        return {
            "action": action,
            "app_key": app_key,
            "spec": spec,
            "kanban": kanban,
            "view": selected_view,
            "search": search,
            "records": records,
            "groups": groups,
            "fields_meta": model.fields_get(),
            "q": q,
            "selected_filter": selected,
            "selected_group": selected_group,
            "total": total,
            "offset": offset,
            "limit": PAGE_SIZE,
            "prev_offset": max(offset - PAGE_SIZE, 0),
            "next_offset": (
                offset + PAGE_SIZE
                if not selected_group and offset + PAGE_SIZE < total
                else None
            ),
            "menu_id": menu_id,
            "breadcrumbs": self._breadcrumbs(env, app_key, menu_id, action["name"]),
            "can_create": can_create,
            "can_write": self._can(env, model_name, "write"),
            "can_unlink": can_delete,
            "base_url": base_url,
        }

    def _decorate_records(
        self, env: Env, model_name: str, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add the virtual statistics column without a query per row."""
        if model_name != "core.partner" or not records:
            return records
        partner_model: Any = env["core.partner"]
        stats = partner_model.statistics([record["id"] for record in records])
        for record in records:
            record["statistics"] = stats.get(
                record["id"], {"addresses": 0, "bank_accounts": 0}
            )
        return records

    def _text_domain(self, search_fields: list[dict[str, Any]], q: str) -> list[Any]:
        names = [f["name"] for f in search_fields] or ["name"]
        leaves = [(name, "ilike", q) for name in names]
        if len(leaves) == 1:
            return leaves
        return ["|"] * (len(leaves) - 1) + leaves

    def _app_menus(self, env: Env, app_key: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        root = self._app_root_menu(env, app_key)
        return self._menu_tree(env, root["id"], user, app_key) if root else []

    # -- routes: forms -----------------------------------------------------
    def on_form_new(self, request: Request, app_key: str, action_id: int) -> Response:
        return self._form(request, app_key, action_id, None)

    def on_form_edit(self, request: Request, app_key: str, action_id: int, record_id: int) -> Response:
        return self._form(request, app_key, action_id, record_id)

    def _form(
        self, request: Request, app_key: str, action_id: int, record_id: int | None
    ) -> Response:
        env = self._env(request)
        state = self._require_state(request)
        action = self._resolve_action(env, action_id)
        model_name = action["res_model"]
        model = env[model_name]
        view_row = self._resolve_view(env, model_name, "form")
        if view_row is None:
            raise NotFound(f"no form view for {model_name}")
        arch = views.parse_arch(view_row["arch"])

        if request.method == "POST":
            self._check_csrf(request)
            raw_specs = self._form_specs(env, model, arch, {})
            payload = views.coerce_form_values(
                model, raw_specs, request.form, creating=record_id is None
            )
            try:
                if record_id is None:
                    new_id = model.create(payload)
                    self._note(env.uid, model_name, new_id, f"{model._description} created.")
                    self.auth.add_flash(state["token"], "Record created.")
                    return redirect(f"/apps/{app_key}/action/{action_id}/{new_id}")
                model.write([record_id], payload)
                self._note(env.uid, model_name, record_id, f"{model._description} updated.")
                self.auth.add_flash(state["token"], "Record saved.")
                return redirect(f"/apps/{app_key}/action/{action_id}/{record_id}")
            except (ValidationError, AccessError) as exc:
                self.auth.add_flash(state["token"], str(exc), "danger")
                target = (
                    f"/apps/{app_key}/action/{action_id}/new"
                    if record_id is None
                    else f"/apps/{app_key}/action/{action_id}/{record_id}"
                )
                return redirect(target)

        data = self._form_payload(
            env,
            app_key,
            action_id,
            record_id,
            menu_id=request.args.get("menu", type=int),
        )
        return self._render(
            "form.html",
            self._context(
                request,
                title=f"{action['name']} - KB ERP",
                current_app={"key": app_key, "name": self._app_name(app_key)},
                menus=self._app_menus(env, app_key, state["user"]),
                **data,
            ),
        )

    def _form_payload(
        self,
        env: Env,
        app_key: str,
        action_id: int,
        record_id: int | None,
        *,
        menu_id: int | None = None,
    ) -> dict[str, Any]:
        action = self._resolve_action(env, action_id)
        model_name = action["res_model"]
        model = env[model_name]
        view_row = self._resolve_view(env, model_name, "form")
        if view_row is None:
            raise NotFound(f"no form view for {model_name}")
        arch = views.parse_arch(view_row["arch"])

        values: dict[str, Any] = {}
        messages: list[dict[str, Any]] = []
        followers: list[dict[str, Any]] = []
        activities: list[dict[str, Any]] = []
        smart_buttons: list[dict[str, Any]] = []
        if record_id is not None:
            rows = model.read([record_id])
            if not rows:
                raise NotFound("record not found")
            values = rows[0]
            message_model = env["chatter.message"]
            message_ids = message_model.search(
                [("model", "=", model_name), ("res_id", "=", record_id)],
                order="-id",
                limit=20,
            )
            messages = message_model.read(message_ids)
            follower_model = env["chatter.follower"]
            follower_ids = follower_model.search(
                [("model", "=", model_name), ("res_id", "=", record_id)],
                order="-id",
            )
            followers = follower_model.read(follower_ids)
            activity_model = env["chatter.activity"]
            activity_ids = activity_model.search(
                [
                    ("model", "=", model_name),
                    ("res_id", "=", record_id),
                    ("state", "=", "planned"),
                ],
                order="date_deadline, id",
            )
            activities = activity_model.read(activity_ids)
            smart_buttons = self._smart_buttons(env, model_name, record_id)
        else:
            values = views.form_defaults(model, arch)
            self._apply_action_defaults(action, values)
        activity_types = env["chatter.activity_type"].read(
            env["chatter.activity_type"].search([], order="name")
        )
        spec = views.form_spec(env, model, arch, values)
        self._decorate_buttons(
            model_name,
            spec["buttons"],
            values.get("state"),
            values.get("locked"),
            values,
        )
        title = (
            values.get("name") or f"Record {record_id}"
            if record_id is not None
            else f"New {spec['string'].lower()}"
        )
        base_url = f"/apps/{app_key}/action/{action_id}"
        return {
            "action": action,
            "app_key": app_key,
            "spec": spec,
            "record_id": record_id,
            "record": values,
            "messages": messages,
            "followers": followers,
            "activities": activities,
            "activity_types": activity_types,
            "smart_buttons": smart_buttons,
            "fields_meta": model.fields_get(),
            "menu_id": menu_id,
            "breadcrumbs": self._breadcrumbs(env, app_key, menu_id, action["name"]),
            "base_url": base_url,
            "record_url": f"{base_url}/{record_id}" if record_id is not None else f"{base_url}/new",
            "title_text": title,
            "can_create": self._can(env, model_name, "create"),
            "can_write": self._can(env, model_name, "write")
            and not (model_name == "accounting.move" and values.get("state") == "posted")
            and not (model_name == "inventory.picking" and values.get("state") in ("done", "cancel")),
            "can_unlink": self._can(env, model_name, "unlink"),
        }

    @staticmethod
    def _apply_action_defaults(action: dict[str, Any], values: dict[str, Any]) -> None:
        """Materialise simple equality leaves from an action domain as defaults."""
        for leaf in views.parse_domain(action.get("domain")):
            if (
                isinstance(leaf, (list, tuple))
                and len(leaf) == 3
                and leaf[1] == "="
                and isinstance(leaf[0], str)
            ):
                values[leaf[0]] = leaf[2]

    @staticmethod
    def _decorate_buttons(
        model_name: str,
        buttons: list[dict[str, Any]],
        state: Any,
        locked: Any = False,
        record: dict[str, Any] | None = None,
    ) -> None:
        record = record or {}
        for button in buttons:
            name = button["name"]
            if model_name == "sales.order":
                visible = (
                    (name == "action_send" and state == "draft")
                    or (name == "action_confirm" and state in ("draft", "sent"))
                    or (name == "action_cancel" and state in ("draft", "sent", "sale"))
                    or (name == "action_reset" and state == "cancel")
                    or (name == "action_invoice" and state == "sale")
                    or (name == "action_lock" and state == "sale" and not locked)
                    or (name == "action_unlock" and state == "sale" and locked)
                )
            elif model_name == "purchase.order":
                waiting = record.get("approval_state") == "waiting"
                visible = (
                    (name == "action_send" and state == "draft" and not waiting)
                    or (
                        name == "action_confirm"
                        and state in ("draft", "sent")
                        and not waiting
                    )
                    or (name == "action_approve" and waiting)
                    or (name == "action_reject" and waiting)
                    or (name == "action_cancel" and state in ("draft", "sent", "purchase"))
                    or (name == "action_create_bill" and state == "purchase")
                    or (name == "action_lock" and state == "purchase" and not locked)
                    or (name == "action_unlock" and state == "purchase" and locked)
                )
            elif model_name == "purchase.agreement":
                visible = (
                    (name == "action_start" and state == "draft")
                    or (name == "action_call_off" and state == "running")
                    or (name == "action_close" and state in ("draft", "running"))
                    or (name == "action_cancel" and state not in ("cancel", "closed"))
                )
            elif model_name == "purchase.landed_cost":
                visible = name == "action_post" and state == "draft"
            elif model_name == "purchase.analysis":
                visible = name == "action_run"
            elif model_name == "accounting.asset":
                visible = name in ("action_compute", "action_post_depreciation") and state in (
                    "draft",
                    "running",
                )
            elif model_name == "accounting.loan":
                visible = name in ("action_compute", "action_post_payments") and state in (
                    "draft",
                    "running",
                )
            elif model_name == "accounting.deferral":
                visible = name in ("action_compute", "action_post") and state in (
                    "draft",
                    "running",
                )
            elif model_name == "accounting.tax_return":
                visible = name == "action_compute" and state == "draft"
            elif model_name == "accounting.bank_statement":
                visible = (
                    name == "action_import" and state in ("draft", "imported")
                ) or (name == "action_match" and state == "imported")
            elif model_name == "accounting.report":
                visible = name == "action_run"
            elif model_name == "accounting.move":
                move_type = record.get("move_type")
                residual = float(record.get("amount_residual") or 0)
                visible = (
                    (name == "action_post" and state == "draft")
                    or (name == "action_cancel" and state in ("draft", "posted"))
                    or (name == "action_reverse" and state == "posted")
                    or (
                        name in ("action_register_payment", "action_credit_note")
                        and state == "posted"
                    )
                    or (
                        name == "action_secure"
                        and state == "posted"
                        and not record.get("secured")
                    )
                    or (
                        name == "action_send_followup"
                        and move_type == "out_invoice"
                        and state == "posted"
                        and residual > 0
                    )
                    or (
                        name == "action_generate_etims"
                        and move_type in ("out_invoice", "out_refund")
                        and state == "posted"
                    )
                    or (
                        name == "action_write_off"
                        and move_type == "out_invoice"
                        and state == "posted"
                        and residual > 0
                    )
                )
            elif model_name == "inventory.orderpoint":
                visible = name == "action_replenish"
            else:
                visible = (
                    (name in ("action_check", "action_validate") and state in ("draft", "assigned"))
                    or (name == "action_cancel" and state not in ("done", "cancel"))
                )
            button["visible"] = visible

    def _save_payload(
        self,
        env: Env,
        action_id: int,
        record_id: int | None,
        values: dict[str, Any],
    ) -> int:
        action = self._resolve_action(env, action_id)
        model_name = action["res_model"]
        model = env[model_name]
        view_row = self._resolve_view(env, model_name, "form")
        if view_row is None:
            raise NotFound(f"no form view for {model_name}")
        arch = views.parse_arch(view_row["arch"])
        raw_specs = self._form_specs(env, model, arch, {})
        payload = views.coerce_values(
            model, raw_specs, values, creating=record_id is None
        )
        if record_id is None:
            new_id = model.create(payload)
            self._note(env.uid, model_name, new_id, f"{model._description} created.")
            return new_id
        model.write([record_id], payload)
        self._note(env.uid, model_name, record_id, f"{model._description} updated.")
        return record_id

    def _note(self, uid: int | None, model_name: str, res_id: int, body: str) -> None:
        """Append a chatter note and make the author follow the record."""
        env = Env(self.db, registry=self.registry, uid=uid, su=True)
        env["chatter.message"].create(
            {
                "model": model_name,
                "res_id": res_id,
                "body": body,
                "author_id": uid,
                "message_type": "note",
            }
        )
        if uid:
            users = env["core.user"].read([uid])
            partner = users[0].get("partner_id") if users else None
            partner_id = partner.get("id") if isinstance(partner, dict) else partner
            if partner_id:
                self._follow(env, model_name, res_id, int(partner_id))

    @staticmethod
    def _follow(env: Env, model_name: str, res_id: int, partner_id: int) -> None:
        followers = env["chatter.follower"]
        existing = followers.search(
            [
                ("model", "=", model_name),
                ("res_id", "=", res_id),
                ("partner_id", "=", partner_id),
            ],
            limit=1,
        )
        if existing:
            followers.write(existing, {"active": True})
        else:
            followers.create(
                {
                    "model": model_name,
                    "res_id": res_id,
                    "partner_id": partner_id,
                    "active": True,
                }
            )

    def _back_to_record(
        self, app_key: str, action_id: int, record_id: int, menu_id: int | None
    ) -> str:
        url = f"/apps/{app_key}/action/{action_id}/{record_id}"
        return f"{url}?menu={menu_id}" if menu_id else url

    # -- routes: chatter ---------------------------------------------------
    def on_chatter_note(
        self, request: Request, app_key: str, action_id: int, record_id: int
    ) -> Response:
        self._check_csrf(request)
        env = self._env(request)
        action = self._resolve_action(env, action_id)
        body = (request.form.get("body") or "").strip()
        token = self._require_state(request)["token"]
        if body:
            author = Env(self.db, registry=self.registry, uid=env.uid, su=True)
            author["chatter.message"].create(
                {
                    "model": action["res_model"],
                    "res_id": record_id,
                    "body": body,
                    "author_id": env.uid,
                    "message_type": "comment",
                }
            )
            self.auth.add_flash(token, "Note added.")
        else:
            self.auth.add_flash(token, "Write something before posting.", "danger")
        return redirect(
            self._back_to_record(
                app_key, action_id, record_id, request.form.get("menu", type=int)
            )
        )

    def on_chatter_follow(
        self, request: Request, app_key: str, action_id: int, record_id: int
    ) -> Response:
        self._check_csrf(request)
        env = self._env(request)
        action = self._resolve_action(env, action_id)
        token = self._require_state(request)["token"]
        su = Env(self.db, registry=self.registry, uid=env.uid, su=True)
        users = su["core.user"].read([env.uid]) if env.uid else []
        partner = users[0].get("partner_id") if users else None
        partner_id = partner.get("id") if isinstance(partner, dict) else partner
        if partner_id:
            self._follow(su, action["res_model"], record_id, int(partner_id))
            self.auth.add_flash(token, "You are following this record.")
        else:
            self.auth.add_flash(
                token, "Your user has no linked contact to follow with.", "danger"
            )
        return redirect(
            self._back_to_record(
                app_key, action_id, record_id, request.form.get("menu", type=int)
            )
        )

    def on_chatter_activity(
        self, request: Request, app_key: str, action_id: int, record_id: int
    ) -> Response:
        self._check_csrf(request)
        env = self._env(request)
        action = self._resolve_action(env, action_id)
        token = self._require_state(request)["token"]
        activity_type = request.form.get("activity_type_id", type=int)
        if not activity_type:
            self.auth.add_flash(token, "Choose an activity type.", "danger")
        else:
            su = Env(self.db, registry=self.registry, uid=env.uid, su=True)
            su["chatter.activity"].create(
                {
                    "model": action["res_model"],
                    "res_id": record_id,
                    "activity_type_id": activity_type,
                    "summary": (request.form.get("summary") or "").strip(),
                    "date_deadline": request.form.get("date_deadline") or None,
                    "note": (request.form.get("note") or "").strip(),
                    "user_id": env.uid,
                    "state": "planned",
                }
            )
            self.auth.add_flash(token, "Activity scheduled.")
        return redirect(
            self._back_to_record(
                app_key, action_id, record_id, request.form.get("menu", type=int)
            )
        )

    def on_chatter_activity_done(
        self,
        request: Request,
        app_key: str,
        action_id: int,
        record_id: int,
        activity_id: int,
    ) -> Response:
        self._check_csrf(request)
        env = self._env(request)
        action = self._resolve_action(env, action_id)
        token = self._require_state(request)["token"]
        su = Env(self.db, registry=self.registry, uid=env.uid, su=True)
        activity_model: Any = su["chatter.activity"]
        rows = activity_model.read([activity_id])
        if (
            not rows
            or rows[0].get("model") != action["res_model"]
            or rows[0].get("res_id") != record_id
        ):
            raise NotFound("activity not found")
        activity_model.complete(activity_id, user_id=env.uid)
        self.auth.add_flash(token, "Activity done.")
        return redirect(
            self._back_to_record(
                app_key, action_id, record_id, request.form.get("menu", type=int)
            )
        )

    def _smart_buttons(
        self, env: Env, model_name: str, record_id: int
    ) -> list[dict[str, Any]]:
        if model_name == "purchase.order":
            order = env["purchase.order"].read([record_id])
            if not order:
                return []
            receipts = env["inventory.picking"].search_count(
                [("origin", "=", order[0]["name"]), ("picking_type", "=", "in")]
            )
            return [{"key": "receipts", "label": "Receipts", "count": receipts}]
        if model_name == "sales.order":
            order = env["sales.order"].read([record_id])
            if not order:
                return []
            deliveries = env["inventory.picking"].search_count(
                [("origin", "=", order[0]["name"]), ("picking_type", "=", "out")]
            )
            return [{"key": "deliveries", "label": "Deliveries", "count": deliveries}]
        if model_name != "core.partner":
            return []
        buttons: list[dict[str, Any]] = []
        for key, label, target, extra in SMART_BUTTONS:
            if target is None:
                count = env["core.partner"].search_count(
                    [("parent_id", "=", record_id)]
                )
            else:
                if target not in env or "partner_id" not in env[target]._fields:
                    continue
                count = env[target].search_count([("partner_id", "=", record_id), *extra])
            buttons.append({"key": key, "label": label, "count": count})
        return buttons

    def _form_specs(self, env: Env, model, arch, values) -> list[dict[str, Any]]:
        spec = views.form_spec(env, model, arch, values)
        groups = list(spec["groups"])
        for page in spec["pages"]:
            groups.extend(page["groups"])
        return [field for group in groups for field in group["fields"]]

    def on_delete_record(
        self, request: Request, app_key: str, action_id: int, record_id: int
    ) -> Response:
        self._check_csrf(request)
        env = self._env(request)
        action = self._resolve_action(env, action_id)
        model = env[action["res_model"]]
        try:
            model.unlink([record_id])
            self.auth.add_flash(self._require_state(request)["token"], "Record deleted.")
        except (ValidationError, AccessError, psycopg.errors.ForeignKeyViolation) as exc:
            self.auth.add_flash(self._require_state(request)["token"], str(exc), "danger")
        return redirect(f"/apps/{app_key}/action/{action_id}")

    def on_object_button(
        self, request: Request, app_key: str, action_id: int, record_id: int, name: str
    ) -> Response:
        self._check_csrf(request)
        env = self._env(request)
        action = self._resolve_action(env, action_id)
        state = self._require_state(request)
        try:
            result = object_actions.invoke(env, action["res_model"], name, record_id)
            self.auth.add_flash(state["token"], result.get("message", "Action completed."))
        except (ValidationError, AccessError, ConflictError) as exc:
            self.auth.add_flash(state["token"], str(exc), "danger")
        target = self._back_to_record(
            app_key,
            action_id,
            record_id,
            request.form.get("menu", type=int),
        )
        return redirect(target)

    def on_object_report(
        self, request: Request, app_key: str, action_id: int, record_id: int, name: str
    ) -> Response:
        env = self._env(request)
        action = self._resolve_action(env, action_id)
        if action["res_model"] == "sales.order" and name == "quotation":
            from ..addons.sales.services.reports import quotation_html

            return Response(
                quotation_html(env, record_id),
                mimetype="text/html",
                headers={"Content-Disposition": f'inline; filename="quotation-{record_id}.html"'},
            )
        if action["res_model"] == "purchase.order" and name == "quotation":
            from ..addons.purchase.services.reports import purchase_html

            return Response(
                purchase_html(env, record_id),
                mimetype="text/html",
                headers={"Content-Disposition": f'inline; filename="purchase-{record_id}.html"'},
            )
        raise NotFound("report not found")

    # -- routes: JSON-RPC --------------------------------------------------
    def on_rpc(self, request: Request) -> Response:
        try:
            payload = json.loads(request.get_data(as_text=True) or "{}")
        except json.JSONDecodeError:
            return self._rpc_error(None, -32700, "Parse error")
        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") or {}
        state = self._state(request)
        if state is None:
            return self._rpc_error(request_id, -32000, "Authentication required")
        if not constant_time_equals(
            request.headers.get("X-CSRF-Token") or "", state["csrf"]
        ):
            return self._rpc_error(request_id, -32000, "Invalid CSRF token")
        try:
            result = self._rpc_dispatch(request, method, params)
        except (
            AccessError,
            ValidationError,
            ConflictError,
            DomainError,
            KeyError,
            NotFound,
            psycopg.errors.ForeignKeyViolation,
        ) as exc:
            return self._rpc_error(request_id, -32000, str(exc))
        return Response(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, default=str),
            mimetype="application/json",
        )

    def _rpc_dispatch(self, request: Request, method: str | None, params: dict[str, Any]):
        env = self._env(request)
        if method == "menu.load":
            app_key = params.get("app") or "contacts"
            state = self._require_state(request)
            return self._app_menus(env, app_key, state["user"])
        if method == "apps.list":
            return self._apps(self._require_state(request)["user"])
        if method == "view.load":
            app_key = str(params.get("app") or "")
            action_id = self._int_param(params, "action_id")
            return self._list_payload(
                env,
                app_key,
                action_id,
                q=str(params.get("q") or ""),
                filter_name=str(params.get("filter") or ""),
                offset=self._int_param(params, "offset", default=0),
                menu_id=self._optional_int(params.get("menu")),
                view=str(params.get("view") or ""),
                group_by=str(params.get("group_by") or ""),
            )
        if method == "view.form":
            app_key = str(params.get("app") or "")
            action_id = self._int_param(params, "action_id")
            return self._form_payload(
                env,
                app_key,
                action_id,
                self._optional_int(params.get("id")),
                menu_id=self._optional_int(params.get("menu")),
            )
        if method == "view.save":
            app_key = str(params.get("app") or "")
            action_id = self._int_param(params, "action_id")
            record_id = self._optional_int(params.get("id"))
            values = params.get("values")
            if not isinstance(values, dict):
                raise ValidationError("values must be an object")
            saved_id = self._save_payload(env, action_id, record_id, values)
            data = self._form_payload(
                env,
                app_key,
                action_id,
                saved_id,
                menu_id=self._optional_int(params.get("menu")),
            )
            data["ok"] = True
            data["id"] = saved_id
            data["message"] = "Record created." if record_id is None else "Record saved."
            return data
        if method == "inventory.scan":
            from ..addons.inventory.services.procurement import scan

            return scan(
                env,
                self._int_param(params, "picking_id"),
                str(params.get("code") or ""),
            )
        if method == "inventory.scheduler":
            from ..addons.inventory.services.procurement import scheduler

            return {"ok": True, "rfq_ids": scheduler(env)}
        if method == "object.action":
            action = self._resolve_action(env, self._int_param(params, "action_id"))
            record_id = self._int_param(params, "id")
            name = str(params.get("name") or "")
            result = object_actions.invoke(env, action["res_model"], name, record_id)
            app_key = str(params.get("app") or "")
            data = self._form_payload(
                env,
                app_key,
                action["id"],
                record_id,
                menu_id=self._optional_int(params.get("menu")),
            )
            return {**result, **data}
        if method == "view.unlink":
            app_key = str(params.get("app") or "")
            action_id = self._int_param(params, "action_id")
            record_id = self._optional_int(params.get("id"))
            if record_id is None:
                raise ValidationError("id is required")
            action = self._resolve_action(env, action_id)
            env[action["res_model"]].unlink([record_id])
            return {
                "ok": True,
                "deleted": 1,
                "message": "Record deleted.",
                "redirect": f"/apps/{app_key}/action/{action_id}",
            }
        if not method:
            raise ValidationError("missing method")
        try:
            prefix, operation = method.split(".", 1)
        except ValueError:
            raise ValidationError(f"unknown method {method!r}") from None
        model = env[params.get("model", "")]
        if prefix != "model" or operation not in {"search_read", "read", "create", "write", "unlink"}:
            raise ValidationError(f"unknown method {method!r}")
        if operation == "search_read":
            domain = params.get("domain") or []
            ids = model.search(domain, order=params.get("order"), limit=params.get("limit", 80))
            return model.read(ids, params.get("fields"))
        if operation == "read":
            return model.read(params.get("ids") or [])
        if operation == "create":
            return {"id": model.create(params.get("values") or {})}
        if operation == "write":
            return {"updated": model.write(params.get("ids") or [], params.get("values") or {})}
        return {"deleted": model.unlink(params.get("ids") or [])}

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"expected an integer, got {value!r}") from exc

    def _int_param(self, params: dict[str, Any], name: str, *, default: int | None = None) -> int:
        value = self._optional_int(params.get(name))
        if value is None:
            if default is not None:
                return default
            raise ValidationError(f"{name} is required")
        return value

    def _rpc_error(self, request_id, code: int, message: str) -> Response:
        return Response(
            json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
            ),
            mimetype="application/json",
            status=200,
        )

    # -- routes: static ----------------------------------------------------
    def on_favicon(self, request: Request) -> Response:
        return redirect("/static/favicon.svg", code=308)

    def on_static(self, request: Request, filename: str) -> Response:
        root = STATIC.resolve()
        candidate = (root / filename).resolve()
        if root not in candidate.parents and candidate != root:
            raise NotFound("static file not found")
        if not candidate.is_file():
            raise NotFound("static file not found")
        mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return Response(
            candidate.read_bytes(), mimetype=mime, headers={"Cache-Control": "max-age=300"}
        )

    # -- errors ------------------------------------------------------------
    def _can(self, env: Env, model: str, mode: str) -> bool:
        try:
            env.check_access(model, mode)
            return True
        except AccessError:
            return False

    def _template_format(self, value: Any, field_type: str, selection: Any = None) -> str:
        meta = {"selection": selection or []}
        return views.format_value(value, field_type, meta)

    def _http_error(self, request: Request, exc: HTTPException) -> Response:
        code = exc.code or 500
        headings = {
            400: "Bad request",
            403: "Access denied",
            404: "Page not found",
            405: "Method not allowed",
        }
        return self._render(
            "error.html",
            self._context(
                request,
                title=f"{code} - KB ERP",
                code=code,
                heading=headings.get(code, exc.name or "Error"),
                message=exc.description or "",
                breadcrumbs=[],
            ),
            status=code,
        )

    def _error_response(self, request: Request, exc: Exception) -> Response:
        if isinstance(exc, AccessError) and request.method in {"GET", "HEAD"}:
            return self._render(
                "error.html",
                self._context(
                    request,
                    title="Access denied - KB ERP",
                    code=403,
                    heading="Access denied",
                    message=str(exc),
                    breadcrumbs=[],
                ),
                status=403,
            )
        if isinstance(exc, (ValidationError, AccessError, DomainError)):
            state = self._state(request)
            if state:
                self.auth.add_flash(state["token"], str(exc), "danger")
                return redirect(self._fallback_url(request))
            return Response(str(exc), status=400, mimetype="text/plain")
        if self.settings.debug:
            import traceback

            return Response(
                f"<h1>500</h1><pre>{traceback.format_exc()}</pre>",
                status=500,
                mimetype="text/html",
            )
        return Response("Internal error", status=500, mimetype="text/plain")

    def _fallback_url(self, request: Request) -> str:
        return request.headers.get("Referer") or "/apps"


def create_app(settings: Settings | None = None) -> Application:
    settings = settings or Settings.from_env()
    return Application(settings)
