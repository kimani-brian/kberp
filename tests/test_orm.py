"""ORM tests: domains, CRUD, validation, audit columns and access control."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from kberp.env import Env
from kberp.orm.domains import DomainError, order_by
from kberp.orm.model import AccessError, ValidationError


def _name(prefix: str = "ORM") -> str:
    return f"{prefix} {uuid.uuid4().hex[:10]}"


def _partner(env, name: str, **values):
    return env["core.partner"].create({"name": name, **values})


# -- domains ---------------------------------------------------------------
def test_domain_or_and_not(env):
    tag = _name("Dom")
    alpha = _partner(env, f"{tag} Alpha")
    beta = _partner(env, f"{tag} Beta")
    gamma = _partner(env, f"{tag} Gamma")

    found = env["core.partner"].search(
        [("name", "like", tag), "|", ("name", "ilike", "alpha"), ("name", "ilike", "beta")]
    )
    assert set(found) == {alpha, beta}

    only_alpha = env["core.partner"].search(
        ["&", ("name", "like", tag), ("name", "ilike", "alpha")]
    )
    assert only_alpha == [alpha]

    not_beta = env["core.partner"].search(["&", ("name", "like", tag), "!", ("name", "ilike", "beta")])
    assert set(not_beta) == {alpha, gamma}

    combined = env["core.partner"].search(["|", ("name", "ilike", "alpha"), ("name", "ilike", "beta")])
    assert {alpha, beta}.issubset(set(combined))
    assert gamma not in combined


def test_domain_in_null_and_like(env):
    tag = _name("Dom")
    first = _partner(env, f"{tag} One", email="one@example.test")
    second = _partner(env, f"{tag} Two")
    third = _partner(env, f"{tag} Three", email="three@example.test")

    found = env["core.partner"].search([("name", "like", tag), ("id", "in", [first, third])])
    assert set(found) == {first, third}

    without_email = env["core.partner"].search(
        [("name", "like", tag), ("email", "=", None)]
    )
    assert without_email == [second]

    with_email = env["core.partner"].search(
        [("name", "like", tag), ("email", "!=", None)]
    )
    assert set(with_email) == {first, third}


def test_domain_rejects_unknown_field(env):
    with pytest.raises(DomainError):
        env["core.partner"].search([("not_a_field", "=", 1)])
    with pytest.raises(DomainError):
        env["core.partner"].search([("name", "regex", "x")])


def test_order_by_compiles_and_rejects(env):
    partner = env["core.partner"]
    assert order_by(partner, "-name, id") == '"name" DESC, "id" ASC'
    with pytest.raises(DomainError):
        order_by(partner, "nope")


def test_search_limit_and_offset(env):
    tag = _name("Page")
    ids = [_partner(env, f"{tag} {i:02d}") for i in range(5)]
    order = env["core.partner"].search([("name", "like", tag)], order="name")
    assert order == ids
    page = env["core.partner"].search([("name", "like", tag)], order="name", limit=2, offset=1)
    assert page == ids[1:3]


# -- CRUD ------------------------------------------------------------------
def test_crud_roundtrip(env):
    partner = env["core.partner"]
    tag = _name("Crud")
    record_id = partner.create({"name": tag, "email": "crud@example.test", "is_company": True})

    rows = partner.read([record_id])
    assert rows[0]["name"] == tag
    assert rows[0]["email"] == "crud@example.test"
    assert rows[0]["is_company"] is True
    assert rows[0]["type"] == "contact"  # model default, not NULL

    partner.write([record_id], {"city": "Mombasa", "email": None})
    refreshed = partner.read([record_id])[0]
    assert refreshed["city"] == "Mombasa"
    assert refreshed["email"] is None

    assert partner.unlink([record_id]) == 1
    assert partner.read([record_id]) == []


def test_many2one_is_expanded_on_read(env):
    tag = _name("M2O")
    company = _partner(env, f"{tag} Ltd", is_company=True)
    person = _partner(env, f"{tag} Person", parent_id=company)
    row = env["core.partner"].read([person])[0]
    assert row["parent_id"] == {"id": company, "name": f"{tag} Ltd"}


def test_audit_columns(env):
    user_id = env["core.user"].search([("login", "=", "admin")], limit=1)[0]
    actor = Env(
        env.db,
        registry=env.registry,
        uid=user_id,
        user={"id": user_id, "login": "admin", "is_admin": True, "group_xmlids": []},
    )
    partner = actor["core.partner"]
    record_id = partner.create({"name": _name("Audit")})
    row = partner.read([record_id])[0]
    assert row["create_uid"]["id"] == user_id
    assert row["write_uid"]["id"] == user_id
    assert row["create_date"] is not None

    partner.write([record_id], {"city": "Nakuru"})
    row = partner.read([record_id])[0]
    assert row["city"] == "Nakuru"
    assert row["write_date"] >= row["create_date"]


def test_required_and_unknown_fields(env):
    partner = env["core.partner"]
    with pytest.raises(ValidationError, match="required"):
        partner.create({})
    with pytest.raises(ValidationError, match="no field"):
        partner.create({"name": _name(), "bogus": 1})
    with pytest.raises(ValidationError, match="no field"):
        partner.read([1], fields=["bogus"])


def test_unique_xml_id(env):
    menus = env["core.ir_ui_menu"]
    menu = {
        "xml_id": f"test.menu_{uuid.uuid4().hex[:8]}",
        "name": "Unique menu",
    }
    record_id = menus.create(menu)
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            menus.create(menu)
    finally:
        menus.unlink([record_id])


# -- access control --------------------------------------------------------
def _restricted_env(env, groups: list[str]) -> Env:
    user_id = env["core.user"].create(
        {
            "name": f"Restricted {uuid.uuid4().hex[:6]}",
            "login": f"restricted-{uuid.uuid4().hex[:8]}",
            "group_xmlids": groups,
        }
    )
    return Env(
        env.db,
        registry=env.registry,
        uid=user_id,
        user={"id": user_id, "login": "restricted", "is_admin": False, "group_xmlids": groups},
    )


def test_acl_read_only_user(env):
    viewer = _restricted_env(env, ["base.group_user"])
    assert viewer["core.partner"].search_count([]) >= 0  # read allowed
    with pytest.raises(AccessError):
        viewer["core.partner"].create({"name": _name("Denied")})
    existing = env["core.partner"].search([], limit=1)[0]
    with pytest.raises(AccessError):
        viewer["core.partner"].write([existing], {"city": "Nowhere"})
    with pytest.raises(AccessError):
        viewer["core.partner"].unlink([existing])


def test_acl_partner_manager_can_write(env):
    manager = _restricted_env(env, ["base.group_user", "base.group_partner_manager"])
    record_id = manager["core.partner"].create({"name": _name("Manager")})
    manager["core.partner"].write([record_id], {"city": "Kisumu"})
    assert manager["core.partner"].unlink([record_id]) == 1


def test_acl_unknown_group_denied(env):
    outsider = _restricted_env(env, ["base.group_user"])
    assert outsider["core.partner"].search_count([]) >= 0
    nobody = Env(
        env.db,
        registry=env.registry,
        uid=None,
        user={"id": None, "login": "nobody", "is_admin": False, "group_xmlids": ["unknown.group"]},
    )
    with pytest.raises(AccessError):
        nobody["core.partner"].search([])
