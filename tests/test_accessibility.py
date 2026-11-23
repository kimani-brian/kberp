"""WCAG 2.2 AA smoke audit for the launcher, list, form and settings screens.

This is a structural check, not a substitute for a manual or axe review: it
enforces the failures that are cheap to prevent and easy to reintroduce —
missing language, landmarks, form labels, duplicate ids and unnamed buttons.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest
from conftest import action_id, login
from werkzeug.test import Client

from kberp.env import Env
from kberp.web.app import Application

CONTACT_ACTION = "contacts.action_partner"


@pytest.fixture()
def admin(client):
    return login(client)


class Audit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lang: str | None = None
        self.mains: list[dict[str, str]] = []
        self.ids: list[str] = []
        self.label_for: list[str] = []
        self.controls: list[dict[str, str]] = []
        self.buttons: list[dict[str, str]] = []
        self._button_stack: list[dict[str, str]] = []
        self._label_depth = 0
        self._control_label_depth: dict[int, int] = {}
        self.images: list[dict[str, str]] = []
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "html":
            self.lang = values.get("lang")
        if tag == "main":
            self.mains.append(values)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "label":
            self._label_depth += 1
            if values.get("for"):
                self.label_for.append(values["for"])
        if tag in {"input", "select", "textarea"}:
            record = {"tag": tag, **values}
            self.controls.append(record)
            self._control_label_depth[id(record)] = self._label_depth
        if tag == "button":
            record = {"tag": "button", **values, "text": ""}
            self.buttons.append(record)
            self._button_stack.append(record)
        if tag == "img":
            self.images.append(values)
        if tag == "h1":
            self.headings.append(values.get("class", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_depth:
            self._label_depth -= 1
        if tag == "button" and self._button_stack:
            self._button_stack.pop()

    def handle_data(self, data: str) -> None:
        for button in self._button_stack:
            button["text"] += data

    def violations(self) -> list[str]:
        problems: list[str] = []
        if self.lang != "en":
            problems.append(f"html lang is {self.lang!r}")
        if len(self.mains) != 1:
            problems.append(f"expected one main landmark, found {len(self.mains)}")
        if not self.ids:
            problems.append("page has no element ids")
        duplicates = {item for item in self.ids if self.ids.count(item) > 1}
        if duplicates:
            problems.append(f"duplicate ids: {sorted(duplicates)}")
        ids = set(self.ids)
        for target in self.label_for:
            if target not in ids:
                problems.append(f"label for={target!r} points at no element")
        for image in self.images:
            if "alt" not in image:
                problems.append(f"img without alt: {image.get('src', '?')}")
        for control in self.controls:
            if control.get("type") == "hidden":
                continue
            name = control.get("name", "")
            if "[" in name:
                continue  # one2many cells are labelled by their table header
            accessible = (
                control.get("aria-label")
                or control.get("aria-labelledby")
                or control.get("title")
                or control.get("id") in set(self.label_for)
                or self._control_label_depth.get(id(control), 0) > 0
            )
            if not accessible:
                problems.append(
                    f"<{control['tag']} name={name!r}> has no label"
                )
        for button in self.buttons:
            if not (button["text"].strip() or button.get("aria-label") or button.get("title")):
                problems.append(f"<button {button.get('class', '')}> has no accessible name")
        if not self.headings:
            problems.append("page has no h1")
        return problems


def audit_page(client: Client, path: str) -> list[str]:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    parser = Audit()
    parser.feed(response.get_data(as_text=True))
    return parser.violations()


def test_login_is_accessible(app: Application):
    assert audit_page(Client(app), "/web/login") == []


def test_launcher_is_accessible(admin: Client):
    assert audit_page(admin, "/apps") == []


def test_app_home_is_accessible(admin: Client):
    assert audit_page(admin, "/apps/contacts") == []


def test_list_is_accessible(admin: Client, env: Env):
    path = f"/apps/contacts/action/{action_id(env, CONTACT_ACTION)}"
    assert audit_page(admin, path) == []


def test_form_is_accessible(admin: Client, env: Env):
    path = f"/apps/contacts/action/{action_id(env, CONTACT_ACTION)}/new"
    assert audit_page(admin, path) == []


def test_settings_is_accessible(admin: Client):
    assert audit_page(admin, "/settings") == []


def test_skip_link_targets_the_main_landmark(admin: Client):
    html = admin.get("/apps").get_data(as_text=True)
    parser = Audit()
    parser.feed(html)
    assert 'href="#main-content"' in html
    assert parser.mains[0].get("id") == "main-content"
