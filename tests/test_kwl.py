"""KWL contracts: list/form payloads and RPC save/delete."""

from __future__ import annotations

import json
import uuid

import pytest
from conftest import action_id, csrf_from, login


def _rpc(client, method, params, token):
    response = client.post(
        "/web/rpc",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
        content_type="application/json",
        headers={"X-CSRF-Token": token},
    )
    return json.loads(response.get_data(as_text=True))


@pytest.fixture()
def admin(client):
    return login(client)


def _contacts(env):
    return action_id(env, "contacts.action_partner")


def test_view_load_matches_the_server_renderer(admin, env):
    aid = _contacts(env)
    token = csrf_from(admin, "/apps")
    payload = _rpc(admin, "view.load", {"app": "contacts", "action_id": aid}, token)
    data = payload["result"]

    assert data["action"]["res_model"] == "core.partner"
    assert data["spec"]["columns"][0]["name"] == "complete_name"
    assert data["total"] >= 3
    assert any(row["name"] == "Apex Logistics Ltd" for row in data["records"])
    assert data["breadcrumbs"][0]["name"] == "Contacts"
    assert data["base_url"] == f"/apps/contacts/action/{aid}"
    assert data["can_create"] is True
    assert data["can_write"] is True
    assert data["limit"] == 40

    filtered = _rpc(
        admin,
        "view.load",
        {"app": "contacts", "action_id": aid, "filter": "companies"},
        token,
    )["result"]
    assert all(row["is_company"] for row in filtered["records"])

    searched = _rpc(
        admin, "view.load", {"app": "contacts", "action_id": aid, "q": "Amina"}, token
    )["result"]
    assert [row["name"] for row in searched["records"]] == ["Amina Wanjiru"]


def test_view_form_and_save_roundtrip(admin, env):
    aid = _contacts(env)
    token = csrf_from(admin, "/apps")
    tag = f"KWL {uuid.uuid4().hex[:8]}"

    empty = _rpc(admin, "view.form", {"app": "contacts", "action_id": aid}, token)["result"]
    assert empty["record_id"] is None
    assert empty["spec"]["groups"]
    assert empty["can_write"] is True

    saved = _rpc(
        admin,
        "view.save",
        {
            "app": "contacts",
            "action_id": aid,
            "values": {
                "name": tag,
                "is_company": True,
                "active": True,
                "type": "contact",
                "email": "kwl@example.test",
            },
        },
        token,
    )
    result = saved["result"]
    record_id = result["id"]
    assert result["ok"] is True
    assert result["message"] == "Record created."
    assert result["record_id"] == record_id
    assert result["record"]["name"] == tag
    assert result["record_url"].endswith(f"/{record_id}")

    row = env["core.partner"].read([record_id])[0]
    assert row["name"] == tag
    notes = env["chatter.message"].search(
        [("model", "=", "core.partner"), ("res_id", "=", record_id)]
    )
    assert len(notes) == 1
    assert env["chatter.message"].read(notes)[0]["body"] == "Contact created."

    edited = _rpc(
        admin,
        "view.save",
        {
            "app": "contacts",
            "action_id": aid,
            "id": record_id,
            "values": {
                "name": tag + " edited",
                "is_company": True,
                "active": True,
                "type": "contact",
                "email": "edited@example.test",
            },
        },
        token,
    )["result"]
    assert edited["message"] == "Record saved."
    assert edited["record"]["name"].endswith("edited")
    assert env["core.partner"].read([record_id])[0]["email"] == "edited@example.test"

    deleted = _rpc(
        admin, "view.unlink", {"app": "contacts", "action_id": aid, "id": record_id}, token
    )["result"]
    assert deleted["deleted"] == 1
    assert deleted["redirect"] == f"/apps/contacts/action/{aid}"
    assert not env["core.partner"].read([record_id])


def test_view_form_applies_model_defaults(admin, env):
    aid = _contacts(env)
    token = csrf_from(admin, "/apps")
    data = _rpc(admin, "view.form", {"app": "contacts", "action_id": aid}, token)["result"]

    assert data["record_id"] is None
    assert data["record"]["active"] is True
    assert data["record"]["type"] == "contact"


def test_view_save_reports_validation_errors(admin, env):
    aid = _contacts(env)
    token = csrf_from(admin, "/apps")
    response = _rpc(
        admin,
        "view.save",
        {"app": "contacts", "action_id": aid, "values": {"name": ""}},
        token,
    )
    assert response["error"]["code"] == -32000
    assert "required" in response["error"]["message"].lower()


def test_view_load_exposes_read_only_permissions(app):
    login_name = f"kwl-viewer-{uuid.uuid4().hex[:8]}"
    app.auth.create_user(login_name, "viewer-pass", "KWL Viewer", ["base.group_user"])
    from werkzeug.test import Client

    viewer = Client(app)
    login(viewer, login_name, "viewer-pass")
    aid = action_id_for(app, "contacts.action_partner")
    token = csrf_from(viewer, "/apps")
    data = _rpc(viewer, "view.load", {"app": "contacts", "action_id": aid}, token)["result"]
    assert data["can_create"] is False
    assert data["can_write"] is False
    assert data["can_unlink"] is False


def action_id_for(app, xml_id):
    from kberp.env import Env

    env = Env(app.db, registry=app.registry, su=True)
    return action_id(env, xml_id)
