"""Web tests: login, launcher, app shells, generic views, ACLs and JSON-RPC."""

from __future__ import annotations

import json
import re
import uuid

import pytest
from conftest import action_id, csrf_from, login


def _html(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def admin(client):
    return login(client)


def _contacts_action(env) -> int:
    return action_id(env, "contacts.action_partner")


# -- authentication --------------------------------------------------------
def test_anonymous_is_redirected_to_login(client):
    response = client.get("/apps")
    assert response.status_code == 302
    assert "/web/login" in response.headers["Location"]


def test_login_rejects_wrong_password(client):
    page = client.get("/web/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', _html(page)).group(1)
    response = client.post(
        "/web/login",
        data={"csrf_token": token, "login": "admin", "password": "wrong"},
    )
    assert response.status_code == 200
    assert "Wrong login or password" in _html(response)


def test_login_without_csrf_is_rejected(client):
    response = client.post("/web/login", data={"login": "admin", "password": "admin"})
    assert response.status_code == 200
    assert "session expired" in _html(response).lower()


def test_login_and_logout_roundtrip(client):
    login(client)
    assert client.get("/apps").status_code == 200
    token = csrf_from(client, "/apps")
    response = client.post("/web/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert client.get("/apps").status_code == 302


def test_login_next_cannot_redirect_off_site(client):
    page = client.get("/web/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', _html(page)).group(1)
    response = client.post(
        "/web/login?next=//evil.example",
        data={"csrf_token": token, "login": "admin", "password": "admin"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/apps"


# -- launcher and shells ---------------------------------------------------
def test_launcher_lists_five_apps_in_sequence(admin):
    html = _html(admin.get("/apps"))
    start = html.index('<section class="launcher-grid"')
    grid = html[start : html.index("</section>", start)]
    positions = [grid.index(name) for name in ("Contacts", "Sales", "Accounting", "Purchase", "Inventory")]
    assert positions == sorted(positions)
    assert grid.count('class="app-card"') == 5
    for key in ("contacts", "sales", "accounting", "purchase", "inventory"):
        assert f'href="/apps/{key}"' in grid


def test_every_app_shell_renders(admin, env):
    aid = _contacts_action(env)
    for key, name in (
        ("contacts", "Contacts"),
        ("sales", "Sales"),
        ("accounting", "Accounting"),
        ("purchase", "Purchase"),
        ("inventory", "Inventory"),
    ):
        response = admin.get(f"/apps/{key}")
        assert response.status_code == 200, key
        assert name in _html(response)
    contacts = _html(admin.get("/apps/contacts"))
    assert f'href="/apps/contacts/action/{aid}' in contacts

    # Sales now ships screens, while the remaining apps still show a shell.
    sales = _html(admin.get("/apps/sales"))
    assert "Quotations" in sales
    assert "/action/" in sales
    accounting = _html(admin.get("/apps/accounting"))
    assert "Ledger at a glance" in accounting
    assert "Invoices" in accounting
    inventory = _html(admin.get("/apps/inventory"))
    assert "Stock at a glance" in inventory
    assert "Receipts" in inventory
    purchase = _html(admin.get("/apps/purchase"))
    assert "Requests for Quotation" in purchase
    shell = _html(admin.get("/apps/inventory"))
    assert "Stock at a glance" in shell


def test_contacts_list_search_and_filter(admin, env):
    aid = _contacts_action(env)
    url = f"/apps/contacts/action/{aid}"

    listing = _html(admin.get(url))
    assert "Apex Logistics Ltd" in listing
    assert "Amina Wanjiru" in listing

    search = _html(admin.get(url + "?q=Amina"))
    assert "Amina Wanjiru" in search
    assert "Acme Trading" not in search

    companies = _html(admin.get(url + "?filter=companies"))
    assert "Apex Logistics Ltd" in companies
    assert "Amina Wanjiru" not in companies

    persons = _html(admin.get(url + "?filter=persons"))
    assert "Amina Wanjiru" in persons
    assert "Acme Trading" not in persons


def test_contacts_list_has_no_n_plus_one(admin, env, app, monkeypatch):
    aid = _contacts_action(env)
    url = f"/apps/contacts/action/{aid}"
    calls: list[str] = []
    original = app.db.fetch_all

    def counting(query, params=None):
        calls.append(str(query))
        return original(query, params)

    monkeypatch.setattr(app.db, "fetch_all", counting)
    assert admin.get(url).status_code == 200
    first = len(calls)

    extra = [
        env["core.partner"].create({"name": f"ZZ Extra {i:02d}"}) for i in range(10)
    ]
    calls.clear()
    try:
        assert admin.get(url).status_code == 200
        second = len(calls)
    finally:
        env["core.partner"].unlink(extra)

    assert second <= first + 1, f"row count changed the query count: {first} -> {second}"
    assert second <= 75, f"list path issued {second} queries"


def test_view_path_comes_from_the_database(admin, env):
    """The renderer never hard-codes labels: it renders the stored arch."""
    aid = _contacts_action(env)
    view = env["core.ir_ui_view"]
    view_id = view.search([("model", "=", "core.partner"), ("type", "=", "list")], limit=1)[0]
    original = view.read([view_id])[0]["arch"]
    renamed = original.replace('string="Email"', 'string="Primary Email"')
    view.write([view_id], {"arch": renamed})
    try:
        html = _html(admin.get(f"/apps/contacts/action/{aid}"))
        assert "Primary Email" in html
        assert '"Email"' not in html
    finally:
        view.write([view_id], {"arch": original})


# -- generic forms ---------------------------------------------------------
def test_create_and_edit_partner_writes_audit_and_chatter(admin, env):
    aid = _contacts_action(env)
    base = f"/apps/contacts/action/{aid}"
    tag = f"Form {uuid.uuid4().hex[:8]}"

    token = csrf_from(admin, base + "/new")
    response = admin.post(
        base + "/new",
        data={
            "csrf_token": token,
            "name": tag,
            "is_company": "on",
            "active": "on",
            "type": "contact",
            "email": "form@example.test",
            "city": "Eldoret",
        },
    )
    assert response.status_code == 302
    location = response.headers["Location"]
    assert re.fullmatch(re.escape(base) + r"/\d+", location)
    record_id = int(location.rsplit("/", 1)[1])

    row = env["core.partner"].read([record_id])[0]
    assert row["name"] == tag
    assert row["is_company"] is True
    assert row["city"] == "Eldoret"
    admin_id = env["core.user"].search([("login", "=", "admin")], limit=1)[0]
    assert row["create_uid"]["id"] == admin_id
    assert row["write_uid"]["id"] == admin_id

    messages = env["chatter.message"].search(
        [("model", "=", "core.partner"), ("res_id", "=", record_id)]
    )
    assert len(messages) == 1
    note = env["chatter.message"].read(messages)[0]
    assert note["body"] == "Contact created."
    assert note["author_id"]["id"] == admin_id

    page = _html(admin.get(location))
    assert tag in page
    assert "Contact created." in page

    edit_token = csrf_from(admin, location)
    response = admin.post(
        location,
        data={
            "csrf_token": edit_token,
            "name": tag + " (edited)",
            "active": "on",
            "type": "contact",
            "email": "edited@example.test",
        },
    )
    assert response.status_code == 302
    row = env["core.partner"].read([record_id])[0]
    assert row["name"].endswith("(edited)")
    assert row["email"] == "edited@example.test"
    assert row["city"] is None  # an empty input clears the field on edit
    notes = env["chatter.message"].search(
        [("model", "=", "core.partner"), ("res_id", "=", record_id)]
    )
    assert len(notes) == 2


def test_required_field_validation(admin, env):
    aid = _contacts_action(env)
    base = f"/apps/contacts/action/{aid}/new"
    token = csrf_from(admin, base)
    response = admin.post(base, data={"csrf_token": token, "name": "", "active": "on"})
    assert response.status_code == 302
    page = _html(admin.get(response.headers["Location"]))
    assert "required" in page.lower()


def test_create_product_through_settings(admin, env):
    aid = action_id(env, "base.action_product_template")
    base = f"/apps/settings/action/{aid}"
    token = csrf_from(admin, base + "/new")
    tag = f"Product {uuid.uuid4().hex[:8]}"
    response = admin.post(
        base + "/new",
        data={
            "csrf_token": token,
            "name": tag,
            "default_code": "TST-001",
            "type": "goods",
            "active": "on",
            "list_price": "1250.50",
            "standard_price": "900",
        },
    )
    assert response.status_code == 302
    ids = env["core.product_template"].search([("name", "=", tag)])
    assert len(ids) == 1
    row = env["core.product_template"].read(ids)[0]
    assert str(row["list_price"]) == "1250.5000"
    assert row["type"] == "goods"


# -- access control --------------------------------------------------------
@pytest.fixture()
def viewer(app):
    login_name = f"viewer-{uuid.uuid4().hex[:8]}"
    app.auth.create_user(login_name, "viewer-pass", "Viewer", ["base.group_user"])
    from werkzeug.test import Client

    client = Client(app)
    login(client, login_name, "viewer-pass")
    return client


def test_restricted_user_cannot_open_settings(viewer):
    response = viewer.get("/settings")
    assert response.status_code == 403
    assert "Access denied" in _html(response)


def test_restricted_user_is_read_only(viewer, env):
    aid = _contacts_action(env)
    listing = viewer.get(f"/apps/contacts/action/{aid}")
    assert listing.status_code == 200
    assert "Apex Logistics Ltd" in _html(listing)

    before = env["core.partner"].search_count([])
    token = csrf_from(viewer, f"/apps/contacts/action/{aid}/new")
    response = viewer.post(
        f"/apps/contacts/action/{aid}/new",
        data={"csrf_token": token, "name": "Forbidden Contact", "active": "on"},
    )
    assert response.status_code == 302
    assert env["core.partner"].search_count([]) == before
    page = _html(viewer.get(response.headers["Location"]))
    assert "cannot create" in page


def test_missing_app_returns_404_page(admin):
    response = admin.get("/apps/does-not-exist")
    assert response.status_code == 404
    assert "Page not found" in _html(response)


def test_static_assets_are_served(admin):
    response = admin.get("/static/css/kberp.css")
    assert response.status_code == 200
    assert ":root" in _html(response)
    assert admin.get("/static/../app.py").status_code == 404


# -- JSON-RPC --------------------------------------------------------------
def _rpc(client, method, params, token):
    return client.post(
        "/web/rpc",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
        content_type="application/json",
        headers={"X-CSRF-Token": token},
    )


def test_rpc_search_read(admin):
    token = csrf_from(admin, "/apps")
    response = _rpc(
        admin,
        "model.search_read",
        {
            "model": "core.partner",
            "domain": [("name", "ilike", "Amina")],
            "fields": ["name", "email"],
            "order": "name",
        },
        token,
    )
    payload = json.loads(_html(response))
    assert payload["result"][0]["name"] == "Amina Wanjiru"
    assert "id" in payload["result"][0]


def test_rpc_requires_authentication(client):
    response = _rpc(
        client,
        "model.search_read",
        {"model": "core.partner"},
        "not-a-token",
    )
    payload = json.loads(_html(response))
    assert payload["error"]["code"] == -32000
    assert "Authentication required" in payload["error"]["message"]


def test_rpc_rejects_bad_csrf(admin):
    response = _rpc(
        admin,
        "model.search_read",
        {"model": "core.partner"},
        "wrong",
    )
    payload = json.loads(_html(response))
    assert "Invalid CSRF token" in payload["error"]["message"]


def test_rpc_create_and_unlink(admin, env):
    token = csrf_from(admin, "/apps")
    tag = f"RPC {uuid.uuid4().hex[:8]}"
    created = json.loads(
        _html(
            _rpc(
                admin,
                "model.create",
                {"model": "core.partner", "values": {"name": tag}},
                token,
            )
        )
    )
    record_id = created["result"]["id"]
    assert env["core.partner"].read([record_id])[0]["name"] == tag
    deleted = json.loads(
        _html(_rpc(admin, "model.unlink", {"model": "core.partner", "ids": [record_id]}, token))
    )
    assert deleted["result"]["deleted"] == 1


# -- C1 form surfaces ------------------------------------------------------
def _create_partner(env, values=None):
    return env["core.partner"].create(
        {"name": f"Test {uuid.uuid4().hex[:8]}", "is_company": True, **(values or {})}
    )


def _clear_chatter(env, model_name: str, res_id: int) -> None:
    every_row = env.with_context(active_test=False)
    for chatter_model in ("chatter.activity", "chatter.follower", "chatter.message"):
        model = every_row[chatter_model]
        ids = model.search([("model", "=", model_name), ("res_id", "=", res_id)])
        if ids:
            model.unlink(ids)


def test_partner_form_renders_tabs_and_smart_buttons(admin, env):
    company = _create_partner(env)
    person = _create_partner(env, {"parent_id": company, "type": "contact"})
    aid = _contacts_action(env)
    url = f"/apps/contacts/action/{aid}/{company}"
    try:
        page = _html(admin.get(url))
        assert 'class="form-tabs"' in page
        for tab in ("Contacts", "Sales &amp; Purchase", "Invoicing", "Notes"):
            assert tab in page
        assert 'class="smart-buttons"' in page
        addresses = re.search(
            r'<div class="smart-button"[^>]*>\s*<strong>(\d+)</strong>\s*<span>Addresses</span>',
            page,
        )
        assert addresses and addresses.group(1) == "1"

        token = csrf_from(admin, url)
        payload = json.loads(
            _html(
                _rpc(
                    admin,
                    "view.form",
                    {"app": "contacts", "action_id": aid, "id": company},
                    token,
                )
            )
        )
        result = payload["result"]
        assert [page["title"] for page in result["spec"]["pages"]] == [
            "Contacts",
            "Sales & Purchase",
            "Invoicing",
            "Notes",
        ]
        assert [button["label"] for button in result["smart_buttons"]] == [
            "Addresses",
            "Bank Accounts",
            "Sales",
            "Purchases",
            "Invoiced",
            "Vendor Bills",
        ]
    finally:
        env["core.partner"].unlink([person, company])


def test_chatter_note_follow_activity_and_done(admin, env):
    partner = _create_partner(env)
    aid = _contacts_action(env)
    url = f"/apps/contacts/action/{aid}/{partner}"
    try:
        token = csrf_from(admin, url)

        response = admin.post(
            f"{url}/note", data={"csrf_token": token, "body": "Called the customer."}
        )
        assert response.status_code == 302
        messages = env["chatter.message"].search(
            [
                ("model", "=", "core.partner"),
                ("res_id", "=", partner),
                ("body", "=", "Called the customer."),
            ]
        )
        assert len(messages) == 1

        response = admin.post(f"{url}/follow", data={"csrf_token": token})
        assert response.status_code == 302
        followers = env["chatter.follower"].search(
            [("model", "=", "core.partner"), ("res_id", "=", partner)]
        )
        assert len(followers) == 1

        activity_type = env["chatter.activity_type"].search([("name", "=", "Call")], limit=1)[0]
        response = admin.post(
            f"{url}/activity",
            data={
                "csrf_token": token,
                "activity_type_id": str(activity_type),
                "summary": "Follow up",
                "date_deadline": "2026-12-01",
                "note": "Ask about the renewal",
            },
        )
        assert response.status_code == 302
        activities = env["chatter.activity"].search(
            [("model", "=", "core.partner"), ("res_id", "=", partner)]
        )
        assert len(activities) == 1
        activity = env["chatter.activity"].read(activities)[0]
        assert activity["summary"] == "Follow up"
        assert str(activity["date_deadline"]) == "2026-12-01"

        # The activity is visible on the form before it is completed.
        page = _html(admin.get(url))
        assert "Follow up" in page
        assert "Schedule an activity" in page

        # An activity cannot be completed through a form for another record.
        other = _create_partner(env)
        try:
            response = admin.post(
                f"/apps/contacts/action/{aid}/{other}/activity/{activities[0]}/done",
                data={"csrf_token": token},
            )
            assert response.status_code == 404
        finally:
            env["core.partner"].unlink([other])

        response = admin.post(f"{url}/activity/{activities[0]}/done", data={"csrf_token": token})
        assert response.status_code == 302
        done = env["chatter.activity"].read(activities)[0]
        assert done["state"] == "done"
        assert done["active"] is False
        notes = env["chatter.message"].search(
            [("model", "=", "core.partner"), ("res_id", "=", partner), ("message_type", "=", "note")]
        )
        assert any("Activity done" in note["body"] for note in env["chatter.message"].read(notes))
    finally:
        _clear_chatter(env, "core.partner", partner)
        env["core.partner"].unlink([partner])


def test_read_only_user_cannot_write_through_rpc(viewer, env):
    partner = env["core.partner"].search([("name", "=", "Apex Logistics Ltd")], limit=1)[0]
    before = env["core.partner"].read([partner])[0]["name"]
    token = csrf_from(viewer, "/apps")
    response = _rpc(
        viewer,
        "model.write",
        {"model": "core.partner", "ids": [partner], "values": {"name": "Hijacked"}},
        token,
    )
    payload = json.loads(_html(response))
    assert payload["error"]["code"] == -32000
    assert "cannot write" in payload["error"]["message"]
    assert env["core.partner"].read([partner])[0]["name"] == before


def test_contacts_list_group_by_country_and_tags(admin, env):
    aid = _contacts_action(env)
    url = f"/apps/contacts/action/{aid}"

    page = _html(admin.get(url + "?group_by=country_id"))
    assert 'class="record-group"' in page
    assert 'class="group-head"' in page
    assert "Kenya" in page
    assert "Group by" in page

    kanban = _html(admin.get(url + "?view=kanban&group_by=country_id"))
    assert 'class="record-group"' in kanban
    assert 'class="kanban-card"' in kanban

    token = csrf_from(admin, "/apps")
    payload = json.loads(
        _html(
            _rpc(
                admin,
                "view.load",
                {
                    "app": "contacts",
                    "action_id": aid,
                    "group_by": "tag_ids",
                },
                token,
            )
        )
    )
    result = payload["result"]
    assert result["selected_group"] == "tag_ids"
    assert result["groups"]
    assert result["records"] == []
    assert all("count" in group and group["records"] for group in result["groups"])
    assert any(group["label"] == "Customer" for group in result["groups"])

    ignored = json.loads(
        _html(
            _rpc(
                admin,
                "view.load",
                {"app": "contacts", "action_id": aid, "group_by": "not_a_field"},
                token,
            )
        )
    )
    assert ignored["result"]["selected_group"] == ""
    assert ignored["result"]["groups"] == []


def test_contacts_list_statistics_column(admin, env):
    company = _create_partner(env)
    address = _create_partner(env, {"parent_id": company, "type": "invoice"})
    bank = env["core.bank"].search([], limit=1)[0]
    account = env["core.bank_account"].create(
        {"partner_id": company, "bank_id": bank, "acc_number": "0123456789"}
    )
    aid = _contacts_action(env)
    try:
        token = csrf_from(admin, "/apps")
        payload = json.loads(
            _html(
                _rpc(
                    admin,
                    "view.load",
                    {"app": "contacts", "action_id": aid},
                    token,
                )
            )
        )
        row = next(r for r in payload["result"]["records"] if r["id"] == company)
        assert row["statistics"] == {"addresses": 1, "bank_accounts": 1}

        page = _html(admin.get(f"/apps/contacts/action/{aid}"))
        assert "1 address" in page
        assert "1 bank" in page

        kanban = _html(admin.get(f"/apps/contacts/action/{aid}?view=kanban"))
        assert "1 address" in kanban
        assert 'class="kanban-stats"' in kanban
    finally:
        env["core.bank_account"].unlink([account])
        env["core.partner"].unlink([address, company])


def test_person_company_radio_renders_and_saves(admin, env):
    aid = _contacts_action(env)
    base = f"/apps/contacts/action/{aid}"

    page = _html(admin.get(base + "/new"))
    assert 'role="radiogroup"' in page
    assert 'value="1"' in page and 'value="0"' in page
    assert "Company" in page and "Person" in page

    token = csrf_from(admin, base + "/new")
    person_name = f"Person {uuid.uuid4().hex[:8]}"
    response = admin.post(
        base + "/new",
        data={"csrf_token": token, "name": person_name, "is_company": "0"},
    )
    assert response.status_code == 302
    person_id = int(response.headers["Location"].rsplit("/", 1)[1])
    person = env["core.partner"].read([person_id])[0]
    assert person["is_company"] is False

    company_name = f"Company {uuid.uuid4().hex[:8]}"
    token = csrf_from(admin, base + "/new")
    response = admin.post(
        base + "/new",
        data={"csrf_token": token, "name": company_name, "is_company": "1"},
    )
    assert response.status_code == 302
    company_id = int(response.headers["Location"].rsplit("/", 1)[1])
    company = env["core.partner"].read([company_id])[0]
    assert company["is_company"] is True

    # The JSON client sends the same strings through view.save.
    token = csrf_from(admin, "/apps")
    payload = json.loads(
        _html(
            _rpc(
                admin,
                "view.save",
                {
                    "app": "contacts",
                    "action_id": aid,
                    "values": {"name": f"RPC Person {uuid.uuid4().hex[:8]}", "is_company": "0"},
                },
                token,
            )
        )
    )
    rpc_id = payload["result"]["id"]
    assert env["core.partner"].read([rpc_id])[0]["is_company"] is False

    env["core.partner"].unlink([rpc_id, company_id, person_id])
