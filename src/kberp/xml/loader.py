"""Odoo-style XML loader for menus, actions, views and security rows.

The dialect is intentionally familiar:

    <odoo>
      <record id="view_partner_list" model="core.ir_ui_view"> ... </record>
      <menuitem id="menu_contacts" name="Contacts" parent="menu_root" action="action_contacts"/>
    </odoo>
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..orm.model import ValidationError


class XMLError(RuntimeError):
    pass


class XMLLoader:
    def __init__(self, env, module: str):
        self.env = env
        self.module = module

    # -- files -------------------------------------------------------------
    def load_file(self, path: Path) -> int:
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            raise XMLError(f"{path.name}: {exc}") from exc
        root = tree.getroot()
        if root.tag != "odoo":
            raise XMLError(f"{path.name}: root element must be <odoo>")
        count = 0
        for element in root:
            try:
                self._process(element)
            except Exception as exc:
                identifier = element.get("id", "?")
                raise XMLError(f"{path.name}: {element.tag} {identifier}: {exc}") from exc
            count += 1
        return count

    # -- elements ----------------------------------------------------------
    def _process(self, element: ET.Element) -> None:
        if element.tag == "record":
            self._record(element)
        elif element.tag == "menuitem":
            self._menuitem(element)
        elif element.tag == "delete":
            self._delete(element)
        else:
            raise XMLError(f"unsupported element <{element.tag}>")

    def _record(self, element: ET.Element) -> None:
        model_name = element.get("model")
        xml_id = element.get("id")
        if not model_name or not xml_id:
            raise XMLError("<record> requires model and id")
        xml_id = self._xml_id(xml_id)
        values: dict[str, Any] = {"xml_id": xml_id}
        for field in element.findall("field"):
            name = field.get("name")
            if not name:
                raise XMLError("<field> without name")
            if field.get("type") == "xml":
                children = list(field)
                if len(children) != 1:
                    raise XMLError(f"<field name={name!r} type='xml'> needs exactly one child")
                values[name] = ET.tostring(children[0], encoding="unicode")
            else:
                values[name] = (field.text or "").strip()

        model = self.env[model_name]
        existing = model.search([("xml_id", "=", xml_id)], limit=1)
        if existing:
            model.write(existing, {k: v for k, v in values.items() if k != "xml_id"})
        else:
            model.create(values)

    def _menuitem(self, element: ET.Element) -> None:
        xml_id = element.get("id")
        name = element.get("name")
        if not xml_id or not name:
            raise XMLError("<menuitem> requires id and name")
        xml_id = self._xml_id(xml_id)
        parent_xml = element.get("parent")
        parent_id = None
        if parent_xml:
            parent_id = self._menu_id(self._xml_id(parent_xml), required=True)

        action_type = None
        action_id = None
        action_xml = element.get("action")
        if action_xml:
            action_type, action_id = self._resolve_action(self._xml_id(action_xml))

        values: dict[str, Any] = {
            "xml_id": xml_id,
            "name": name,
            "parent_id": parent_id,
            "sequence": int(element.get("sequence", "10")),
            "groups": element.get("groups") or "",
            "web_icon": element.get("web_icon") or "",
            "action_xmlid": self._xml_id(action_xml) if action_xml else "",
            "action_type": action_type or "",
            "action_id": action_id,
            "is_app": parent_id is None and element.get("app", "1") != "0",
        }
        model = self.env["core.ir_ui_menu"]
        existing = model.search([("xml_id", "=", xml_id)], limit=1)
        if existing:
            model.write(existing, {k: v for k, v in values.items() if k != "xml_id"})
        else:
            model.create(values)

    def _delete(self, element: ET.Element) -> None:
        model_name = element.get("model")
        xml_id = element.get("id")
        if not model_name or not xml_id:
            raise XMLError("<delete> requires model and id")
        model = self.env[model_name]
        ids = model.search([("xml_id", "=", self._xml_id(xml_id))])
        if ids:
            model.unlink(ids)

    # -- resolution --------------------------------------------------------
    def _resolve_action(self, xml_id: str) -> tuple[str, int]:
        for model_name, action_type in (
            ("core.ir_act_window", "window"),
            ("core.ir_act_client", "client"),
        ):
            model = self.env[model_name]
            ids = model.search([("xml_id", "=", xml_id)], limit=1)
            if ids:
                return action_type, ids[0]
        raise XMLError(f"action {xml_id!r} is not defined before the menu that uses it")

    def _menu_id(self, xml_id: str, *, required: bool = False) -> int | None:
        model = self.env["core.ir_ui_menu"]
        ids = model.search([("xml_id", "=", xml_id)], limit=1)
        if not ids:
            if required:
                raise XMLError(f"parent menu {xml_id!r} is not defined before its child")
            return None
        return ids[0]

    def _xml_id(self, raw: str) -> str:
        raw = raw.strip()
        if not raw:
            raise XMLError("empty xml id")
        return raw if "." in raw else f"{self.module}.{raw}"


def load_module_data(env, module: str, base_path: Path, files: tuple[str, ...]) -> int:
    loader = XMLLoader(env, module)
    total = 0
    for relative in files:
        path = base_path / relative
        if not path.exists():
            raise ValidationError(f"{module}: data file not found: {path}")
        total += loader.load_file(path)
    return total
