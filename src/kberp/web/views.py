"""View parsing and rendering support (list, form, search).

The XML arch is the single source of truth: the renderer never hard-codes a
field. This is what makes `core.ir_ui_view` inheritance possible later.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Any

M2O_LIMIT = 200


class ViewError(ValueError):
    pass


def parse_arch(arch: str) -> ET.Element:
    try:
        return ET.fromstring(arch)
    except ET.ParseError as exc:  # pragma: no cover - loader validates earlier
        raise ViewError(f"invalid view arch: {exc}") from exc


def parse_domain(text: str | None) -> list[Any]:
    if not text:
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError) as exc:
            raise ViewError(f"invalid domain: {text!r}") from exc
    if not isinstance(value, list):
        raise ViewError("domain must be a list")
    return value


def _meta(model, name: str) -> dict[str, Any]:
    fields = model.fields_get()
    if name not in fields:
        raise ViewError(f"{model._name} has no field {name!r}")
    return fields[name]


def list_spec(model, arch: ET.Element) -> dict[str, Any]:
    columns = []
    for node in arch.findall("field"):
        name = node.get("name")
        if not name:
            raise ViewError("<field> without name in list view")
        if name == "statistics" and name not in model._fields:
            # A virtual column: the view asks for counts the server collects in
            # one pass, rather than a stored field.
            columns.append(
                {"name": name, "label": node.get("string") or "Statistics", "type": name}
            )
            continue
        meta = _meta(model, name)
        column = {
            "name": name,
            "label": node.get("string") or meta["string"],
            "type": meta["type"],
        }
        if meta["type"] == "selection":
            column["selection"] = meta.get("selection", [])
        columns.append(column)
    if not columns:
        raise ViewError("list view has no fields")
    return {
        "string": arch.get("string") or model._description,
        "columns": columns,
        "can_create": arch.get("create", "1") != "0",
        "can_delete": arch.get("delete", "1") != "0",
    }


def kanban_spec(model, arch: ET.Element) -> dict[str, Any]:
    """Card fields for the Contacts kanban.

    The engine stays small: a kanban is a named set of fields, rendered as
    cards by the server and by KWL. Boxes and drag-and-drop arrive with later
    phases that need them.
    """
    fields = []
    for node in arch.findall("field"):
        name = node.get("name")
        if not name:
            raise ViewError("<field> without name in kanban view")
        meta = _meta(model, name)
        fields.append(
            {
                "name": name,
                "label": node.get("string") or meta["string"],
                "type": meta["type"],
            }
        )
    if not fields:
        raise ViewError("kanban view has no fields")
    return {
        "string": arch.get("string") or model._description,
        "fields": fields,
    }


def search_spec(model, arch: ET.Element) -> dict[str, Any]:
    search_fields = []
    for node in arch.findall("field"):
        name = node.get("name")
        if not name:
            continue
        meta = _meta(model, name)
        search_fields.append({"name": name, "label": node.get("string") or meta["string"]})
    filters = []
    for node in arch.findall("filter"):
        name = node.get("name") or node.get("string")
        filters.append(
            {
                "name": name,
                "label": node.get("string") or name,
                "domain": parse_domain(node.get("domain") or "[]"),
            }
        )
    group_bys = []
    for node in arch.findall("groupby"):
        name = node.get("name")
        if not name:
            raise ViewError("<groupby> without name in search view")
        meta = _meta(model, name)
        group_bys.append({"name": name, "label": node.get("string") or meta["string"]})
    return {"search_fields": search_fields, "filters": filters, "group_bys": group_bys}


def _iter_form_groups(container: ET.Element):
    """Yield every group in a form, including groups inside notebook pages."""
    for child in container:
        if child.tag == "group":
            yield child
        elif child.tag == "notebook":
            for page in child.findall("page"):
                yield from page.findall("group")


def _render_groups(env, model, groups, values: dict[str, Any]) -> list[dict[str, Any]]:
    rendered = []
    for group in groups:
        fields = []
        for node in group.findall("field"):
            name = node.get("name")
            if not name:
                raise ViewError("<field> without name in form view")
            fields.append(_field_spec(env, model, node, values))
        if fields:
            rendered.append({"title": group.get("string") or "", "fields": fields})
    return rendered


def form_defaults(model, arch: ET.Element) -> dict[str, Any]:
    """Values a new form shows before the user types anything.

    Odoo resolves `default=` on the model, not in the view, so a checkbox such
    as `active` arrives ticked and a date arrives as today. The client only
    sends fields it can see, so defaults must be materialised here.
    """
    sheet = arch.find("sheet")
    container = sheet if sheet is not None else arch
    values: dict[str, Any] = {}
    for node in container.iter("field"):
        name = node.get("name")
        if not name or name not in model._fields or name in values:
            continue
        value = model._fields[name].default_value()
        if value is not None:
            values[name] = value
    return values


def form_spec(env, model, arch: ET.Element, values: dict[str, Any]) -> dict[str, Any]:
    sheet = arch.find("sheet")
    container = sheet if sheet is not None else arch
    buttons = []
    header = arch.find("header")
    if header is not None:
        for node in header.findall("button"):
            name = node.get("name")
            if not name:
                raise ViewError("<button> without name in form header")
            buttons.append(
                {
                    "name": name,
                    "label": node.get("string") or name.replace("action_", "").replace("_", " ").title(),
                }
            )
    reports = [
        {"name": node.get("name"), "label": node.get("string") or node.get("name")}
        for node in arch.findall("report")
        if node.get("name")
    ]
    groups = _render_groups(env, model, list(container.findall("group")), values)
    pages = []
    for notebook in container.findall("notebook"):
        for page in notebook.findall("page"):
            page_groups = _render_groups(env, model, page.findall("group"), values)
            if page_groups:
                pages.append(
                    {"title": page.get("string") or "Page", "groups": page_groups}
                )
    if not groups and not pages:
        groups = _render_groups(env, model, [container], values)
    return {
        "string": arch.get("string") or model._description,
        "buttons": buttons,
        "reports": reports,
        "groups": groups,
        "pages": pages,
    }


def _field_spec(env, model, node: ET.Element, values: dict[str, Any]) -> dict[str, Any]:
    name = node.get("name")
    if not name:
        raise ViewError("<field> without name in form view")
    meta = _meta(model, name)
    raw = values.get(name)
    spec: dict[str, Any] = {
        "name": name,
        "label": node.get("string") or meta["string"],
        "type": meta["type"],
        "widget": node.get("widget") or "",
        "required": bool(meta.get("required")),
        "readonly": bool(meta.get("readonly")) or node.get("readonly") == "1",
        "options": [],
        "value": raw if meta["type"] == "one2many" else _plain_value(raw),
        "rows": node.get("rows") or 3,
    }
    if meta["type"] == "selection":
        spec["options"] = [{"value": v, "label": label} for v, label in meta.get("selection", [])]
    elif meta["type"] in ("many2one", "many2many"):
        relation = meta["relation"]
        ids = env[relation].search([], limit=M2O_LIMIT)
        labels = env[relation].name_by_ids(ids)
        spec["options"] = [{"value": rid, "label": labels.get(rid, str(rid))} for rid in ids]
    elif meta["type"] == "one2many":
        comodel = env[meta["relation"]]
        subview = node.find("list")
        if subview is not None:
            columns = list_spec(comodel, subview)["columns"]
            sub_nodes = {n.get("name"): n for n in subview.findall("field")}
            spec["subfields"] = [
                _field_spec(env, comodel, sub_nodes[column["name"]], {})
                for column in columns
            ]
        else:
            spec["subfields"] = []
        spec["lines"] = raw or []
        spec["editable"] = (subview.get("editable") if subview is not None else None) == "1"
    return spec


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("id")
    if isinstance(value, list):
        return [item.get("id") if isinstance(item, dict) else item for item in value]
    return value


def _parse_line_form(spec: dict[str, Any], form: Any, name: str) -> list[dict[str, Any]]:
    """Read `name[row][field]` inputs back into a list of line values.

    Rows named `new-N` create a line; numeric rows update an existing one. A row
    with its `_delete` box ticked is left out, so the ORM unlinks it.
    """
    prefix = f"{name}["
    rows: dict[str, dict[str, str]] = {}
    for key in form:
        if not key.startswith(prefix) or not key.endswith("]"):
            continue
        inner = key[len(prefix) : -1]
        if "][" not in inner:
            continue
        row_id, field_name = inner.split("][", 1)
        rows.setdefault(row_id, {})[field_name] = form.get(key)
    result: list[dict[str, Any]] = []
    for row_id, fields in rows.items():
        if fields.get("_delete"):
            continue
        line: dict[str, Any] = {}
        if row_id.isdigit():
            line["id"] = int(row_id)
        for sub in spec.get("subfields", []):
            field_name = sub["name"]
            key = f"{name}[{row_id}][{field_name}]"
            line[field_name] = _coerce_line_value(sub, form, key, fields.get(field_name))
        if not _line_is_empty(line):
            result.append(line)
    return result


def _line_is_empty(line: dict[str, Any]) -> bool:
    for name, value in line.items():
        if name == "id":
            continue
        if value in (None, "", [], 0, "0", False):
            continue
        return False
    return True


def _coerce_line_value(
    spec: dict[str, Any], form: Any, key: str, raw: str | None
) -> Any:
    if spec["type"] == "boolean":
        return bool(raw)
    if spec["type"] == "many2many":
        return [int(v) for v in form.getlist(key) if str(v).strip()]
    if spec["type"] in ("integer", "float", "monetary"):
        text = (raw or "").strip()
        if not text:
            return None
        return int(text) if spec["type"] == "integer" else text
    return (raw or "").strip()


def coerce_form_values(
    model, specs: list[dict[str, Any]], form: Any, *, creating: bool = False
) -> dict[str, Any]:
    """Turn an HTML form into model values, keeping field types honest.

    On create an empty input means "use the model default", which is what the
    user sees in an Odoo form. On edit an empty input deliberately clears the
    field, so an explicit `None` is sent instead.
    """
    values: dict[str, Any] = {}
    for spec in specs:
        if spec["readonly"]:
            continue
        name = spec["name"]
        if spec["type"] == "one2many":
            values[name] = _parse_line_form(spec, form, name)
            continue
        if spec["type"] == "boolean":
            if name not in form:
                values[name] = False
            else:
                raw = form.get(name)
                values[name] = (
                    raw
                    if isinstance(raw, bool)
                    else str(raw).strip().lower() in {"1", "true", "on", "yes"}
                )
            continue
        if spec["type"] == "many2many":
            values[name] = [int(v) for v in form.getlist(name) if str(v).strip()]
            continue
        raw = (form.get(name) or "").strip()
        if raw == "":
            if creating and model._fields[name].default_value() is not None:
                continue
            values[name] = None
            continue
        values[name] = raw
    return values


def coerce_values(
    model, specs: list[dict[str, Any]], values: dict[str, Any], *, creating: bool = False
) -> dict[str, Any]:
    """The JSON counterpart of :func:`coerce_form_values`.

    The browser sends booleans as booleans and everything else as strings; the
    server still normalises empties and leaves defaults to the model on create.
    """
    result: dict[str, Any] = {}
    for spec in specs:
        if spec["readonly"]:
            continue
        name = spec["name"]
        if spec["type"] == "one2many":
            lines = values.get(name) or []
            result[name] = []
            for line in lines if isinstance(lines, list) else []:
                item = dict(line) if isinstance(line, dict) else {}
                if item.get("id") not in (None, ""):
                    item["id"] = int(item["id"])
                if not _line_is_empty(item):
                    result[name].append(item)
            continue
        if spec["type"] == "boolean":
            if creating and name not in values:
                continue
            raw = values.get(name)
            result[name] = (
                raw
                if isinstance(raw, bool)
                else str(raw).strip().lower() in {"1", "true", "on", "yes"}
            )
            continue
        if spec["type"] == "many2many":
            raw_ids = values.get(name) or []
            if isinstance(raw_ids, (str, int)):
                raw_ids = [raw_ids]
            result[name] = [int(v) for v in raw_ids if str(v).strip()]
            continue
        raw = values.get(name)
        if isinstance(raw, str):
            raw = raw.strip()
        if raw in (None, ""):
            if creating and model._fields[name].default_value() is not None:
                continue
            result[name] = None
            continue
        result[name] = raw
    return result


def format_value(value: Any, field_type: str, meta: dict[str, Any] | None = None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if field_type == "boolean":
        return "Yes" if value else "No"
    if field_type in ("monetary", "float"):
        try:
            number = Decimal(str(value))
        except (ArithmeticError, ValueError, TypeError):
            return str(value)
        return f"{number:,.2f}"
    if field_type == "integer":
        return f"{int(value):,}"
    if field_type == "selection" and meta:
        return dict(meta.get("selection", [])).get(value, str(value))
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    return str(value)
