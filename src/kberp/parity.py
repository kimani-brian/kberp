"""Parity and metadata checks used by CI.

`menus` compares the live menu tree with the committed P0 fixture; `views`
validates that every stored view, action and menu points at something real.
Both are deliberately small and explicit so a failure says exactly what drifted.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .config import BASE_DIR
from .orm.fields import One2many

PROJECT_ROOT = BASE_DIR.parents[1]
DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "parity" / "menus.json"
ACTIONS_FIXTURE = PROJECT_ROOT / "tests" / "parity" / "actions.json"

# Columns the view renderer supplies without a stored model field.
VIRTUAL_FIELDS = {
    "core.partner": {"statistics"},
}


class ParityError(RuntimeError):
    pass


# -- menus -----------------------------------------------------------------
def menu_snapshot(env) -> list[dict[str, Any]]:
    menus = env["core.ir_ui_menu"]
    ids = menus.search([], order="sequence, id")
    rows = menus.read(ids)
    by_id = {
        row["id"]: (row["parent_id"]["id"] if isinstance(row["parent_id"], dict) else row["parent_id"])
        for row in rows
    }
    snapshot = []
    for row in rows:
        parent_id = by_id.get(row["id"])
        parent = next((r["xml_id"] for r in rows if r["id"] == parent_id), None)
        snapshot.append(
            {
                "xml_id": row["xml_id"],
                "name": row["name"],
                "parent": parent,
                "sequence": int(row["sequence"] or 0),
                "is_app": bool(row["is_app"]),
                "web_icon": row["web_icon"] or "",
                "action": row["action_xmlid"] or "",
                "groups": row["groups"] or "",
            }
        )
    return sorted(snapshot, key=lambda item: item["xml_id"])


def load_fixture(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_FIXTURE
    if not path.exists():
        raise ParityError(f"menu fixture not found: {path}")
    return json.loads(path.read_text())


def diff_menus(snapshot: list[dict[str, Any]], fixture: dict[str, Any]) -> list[str]:
    expected = {item["xml_id"]: item for item in fixture.get("menus", [])}
    actual = {item["xml_id"]: item for item in snapshot}
    problems: list[str] = []

    for xml_id in sorted(expected.keys() - actual.keys()):
        problems.append(f"missing menu {xml_id}")
    for xml_id in sorted(actual.keys() - expected.keys()):
        problems.append(f"unexpected menu {xml_id}")
    for xml_id in sorted(expected.keys() & actual.keys()):
        for key, value in expected[xml_id].items():
            if actual[xml_id].get(key) != value:
                problems.append(
                    f"{xml_id}.{key}: expected {value!r}, found {actual[xml_id].get(key)!r}"
                )

    expected_order = list(fixture.get("root_order", []))
    actual_order = [
        item["xml_id"]
        for item in sorted(snapshot, key=lambda i: (i["sequence"], i["xml_id"]))
        if item["parent"] is None
    ]
    if expected_order and actual_order != expected_order:
        problems.append(f"root order: expected {expected_order}, found {actual_order}")
    return problems


def check_menus(env, fixture_path: Path | None = None) -> None:
    problems = diff_menus(menu_snapshot(env), load_fixture(fixture_path))
    if problems:
        raise ParityError("menu parity diff:\n  " + "\n  ".join(problems))


# -- views, actions and menus ----------------------------------------------
def _check_view_fields(node, model, row, models, problems) -> None:
    """Validate field names, descending into a one2many subview with its model."""
    child_model = model
    if node.tag == "field":
        name = node.get("name")
        if name:
            field = model._fields.get(name)
            if field is None:
                if name not in VIRTUAL_FIELDS.get(row["model"], set()):
                    problems.append(f"{row['xml_id']}: {row['model']} has no field {name!r}")
            elif isinstance(field, One2many):
                child_model = models.get(field.comodel) or model
    for child in node:
        _check_view_fields(child, child_model, row, models, problems)


def check_views(env) -> None:
    problems: list[str] = []
    models = env.registry.models

    views = env["core.ir_ui_view"]
    view_rows = views.read(views.search([]))
    by_model: dict[str, set[str]] = {}
    for row in view_rows:
        model = models.get(row["model"])
        if model is None:
            problems.append(f"{row['xml_id']}: unknown model {row['model']}")
            continue
        try:
            arch = ET.fromstring(row["arch"])
        except ET.ParseError as exc:
            problems.append(f"{row['xml_id']}: invalid XML ({exc})")
            continue
        if arch.tag != row["type"]:
            problems.append(
                f"{row['xml_id']}: type is {row['type']!r} but root element is <{arch.tag}>"
            )
        _check_view_fields(arch, model, row, models, problems)
        by_model.setdefault(row["model"], set()).add(row["type"])

    actions = env["core.ir_act_window"]
    action_rows = actions.read(actions.search([]))
    action_ids = {row["xml_id"] for row in action_rows}
    for row in action_rows:
        if row["res_model"] not in models:
            problems.append(f"{row['xml_id']}: unknown model {row['res_model']}")
            continue
        available = by_model.get(row["res_model"], set())
        for needed in ("list", "form"):
            if needed in (row["view_mode"] or "") and needed not in available:
                problems.append(f"{row['xml_id']}: {row['res_model']} has no {needed} view")

    clients = env["core.ir_act_client"]
    client_ids = {row["xml_id"] for row in clients.read(clients.search([]))}

    menus = env["core.ir_ui_menu"]
    menu_rows = menus.read(menus.search([]))
    menu_ids = {row["xml_id"] for row in menu_rows}
    for row in menu_rows:
        action = row["action_xmlid"]
        if not action:
            continue
        known = action_ids if row["action_type"] == "window" else client_ids
        if action not in known:
            problems.append(
                f"{row['xml_id']}: action {action!r} is not a {row['action_type']} action"
            )
        if row["action_id"] is None:
            problems.append(f"{row['xml_id']}: action {action!r} has no id")
        if row["is_app"] and action not in client_ids:
            problems.append(f"{row['xml_id']}: app root must use a client action, not {action!r}")

    for row in menu_rows:
        parent = row["parent_id"]
        parent_id = parent["id"] if isinstance(parent, dict) else parent
        if parent_id is not None:
            parent_xml = next((m["xml_id"] for m in menu_rows if m["id"] == parent_id), None)
            if parent_xml is None or parent_xml not in menu_ids:
                problems.append(f"{row['xml_id']}: parent menu does not exist")

    if problems:
        raise ParityError("view/menu check failed:\n  " + "\n  ".join(problems))


# -- actions, apps and settings --------------------------------------------
def action_snapshot(env) -> list[dict[str, Any]]:
    """Every window action with the labels the menu and breadcrumbs show."""
    actions = env["core.ir_act_window"]
    rows = actions.read(actions.search([], order="id"))
    return sorted(
        (
            {
                "xml_id": row["xml_id"],
                "name": row["name"],
                "model": row["res_model"],
                "view_mode": row["view_mode"] or "",
                "domain": row["domain"] or "[]",
                "path": row["path"] or "",
            }
            for row in rows
        ),
        key=lambda item: item["xml_id"],
    )


def diff_actions(snapshot: list[dict[str, Any]], fixture: dict[str, Any]) -> list[str]:
    expected = {item["xml_id"]: item for item in fixture.get("actions", [])}
    actual = {item["xml_id"]: item for item in snapshot}
    problems: list[str] = []
    for xml_id in sorted(expected.keys() - actual.keys()):
        problems.append(f"missing action {xml_id}")
    for xml_id in sorted(actual.keys() - expected.keys()):
        problems.append(f"unexpected action {xml_id}")
    for xml_id in sorted(expected.keys() & actual.keys()):
        for key, value in expected[xml_id].items():
            if actual[xml_id].get(key) != value:
                problems.append(
                    f"{xml_id}.{key}: expected {value!r}, found {actual[xml_id].get(key)!r}"
                )
    return problems


def app_snapshot(env) -> list[dict[str, Any]]:
    """Each launcher app with the size of its menu subtree."""
    menus = menu_snapshot(env)
    children: dict[str | None, list[str]] = {}
    for row in menus:
        children.setdefault(row["parent"], []).append(row["xml_id"])

    def descendants(xml_id: str) -> int:
        total = 0
        for child in children.get(xml_id, []):
            total += 1 + descendants(child)
        return total

    return [
        {
            "key": manifest.name,
            "name": manifest.label,
            "sequence": manifest.sequence,
            "summary": manifest.summary,
            "icon": manifest.icon,
            "menus": descendants(f"{manifest.name}.menu_{manifest.name}_root"),
        }
        for manifest in env.registry.apps()
    ]


def settings_groups(env) -> list[str]:
    """Top-level settings groups, in menu order."""
    snapshot = menu_snapshot(env)
    root = next(
        (item["xml_id"] for item in snapshot if item["xml_id"] == "base.menu_settings_root"),
        None,
    )
    if root is None:
        return []
    return [item["name"] for item in snapshot if item["parent"] == root]


def _score(expected: int, problems: list[str]) -> float:
    """A percentage that stays honest when extra or missing rows appear."""
    if not problems:
        return 100.0
    return round(max(0.0, (expected - len(problems)) / max(expected, 1)) * 100, 1)


def parity_report(
    env, fixture_path: Path | None = None, actions_path: Path | None = None
) -> dict[str, Any]:
    """A single scorecard for menus, action labels, apps and settings groups."""
    menus = menu_snapshot(env)
    menu_fixture = load_fixture(fixture_path)
    expected_menus = len(menu_fixture.get("menus", []))
    menu_problems = diff_menus(menus, menu_fixture)

    actions = action_snapshot(env)
    actions_path = actions_path or ACTIONS_FIXTURE
    action_fixture = json.loads(actions_path.read_text()) if actions_path.exists() else {"actions": []}
    expected_actions = len(action_fixture.get("actions", []))
    action_problems = diff_actions(actions, action_fixture) if actions_path.exists() else []
    unlabelled = [item["xml_id"] for item in actions if not item["name"].strip()]

    apps = app_snapshot(env)
    app_problems = [
        f"{app['key']}: missing name, summary, sequence or menus"
        for app in apps
        if not app["name"] or not app["summary"] or not app["sequence"] or not app["menus"]
    ]
    groups = settings_groups(env)
    settings_problems = [] if groups else ["Settings menu has no groups"]

    problems = menu_problems + action_problems + unlabelled + app_problems + settings_problems
    return {
        "ok": not problems,
        "menus": {
            "total": len(menus),
            "expected": expected_menus,
            "score": _score(expected_menus, menu_problems),
            "problems": menu_problems,
        },
        "actions": {
            "total": len(actions),
            "expected": expected_actions,
            "score": _score(expected_actions, action_problems),
            "unlabelled": unlabelled,
            "problems": action_problems,
        },
        "apps": apps,
        "settings_groups": groups,
        "problems": problems,
    }


def check_parity(env, fixture_path: Path | None = None, actions_path: Path | None = None) -> dict[str, Any]:
    report = parity_report(env, fixture_path, actions_path)
    if report["problems"]:
        raise ParityError("parity check failed:\n  " + "\n  ".join(report["problems"]))
    return report
