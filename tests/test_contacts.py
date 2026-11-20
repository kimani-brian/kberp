"""C1 contact invariants: hierarchy, sync, tags, banks and safeguards."""

from __future__ import annotations

import uuid

import pytest

from kberp.orm.model import ValidationError


def _name(prefix: str = "C1") -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


@pytest.fixture()
def partners(env):
    return env["core.partner"]


def test_partner_kind_complete_name_and_commercial(env, partners):
    company = partners.create({"name": _name("Company"), "is_company": True})
    person = partners.create(
        {"name": _name("Person"), "parent_id": company, "type": "contact"}
    )

    rows = {row["id"]: row for row in partners.read([company, person])}
    assert rows[company]["complete_name"] == rows[company]["name"]
    assert rows[person]["complete_name"] == f"{rows[company]['name']}, {rows[person]['name']}"
    assert rows[person]["commercial_partner_id"]["id"] == company
    assert rows[company]["commercial_partner_id"]["id"] == company

    partners.unlink([person, company])


def test_contact_requires_a_name(env, partners):
    with pytest.raises(ValidationError):
        partners.create({"name": "", "type": "contact"})


def test_address_sync_company_to_contact_children_only(partners):
    company = partners.create(
        {"name": _name("Address Co"), "is_company": True, "street": "Old Road"}
    )
    person = partners.create(
        {"name": _name("Address Person"), "parent_id": company, "type": "contact"}
    )
    invoice = partners.create(
        {
            "name": _name("Invoice Address"),
            "parent_id": company,
            "type": "invoice",
            "street": "Old Road",
        }
    )

    partners.write([company], {"street": "New Road", "city": "Nairobi"})

    rows = {row["id"]: row for row in partners.read([company, person, invoice])}
    assert rows[person]["street"] == "New Road"
    assert rows[person]["city"] == "Nairobi"
    assert rows[invoice]["street"] == "Old Road"
    assert rows[invoice]["city"] is None

    partners.unlink([person, invoice, company])


def test_vat_syncs_up_to_the_company(partners):
    company = partners.create({"name": _name("VAT Co"), "is_company": True})
    person = partners.create(
        {"name": _name("VAT Person"), "parent_id": company, "type": "contact"}
    )

    partners.write([person], {"vat": "KE-VAT-001"})

    assert partners.read([company])[0]["vat"] == "KE-VAT-001"
    partners.unlink([person, company])


def test_parent_cycle_is_rejected(partners):
    parent = partners.create({"name": _name("Cycle Parent"), "is_company": True})
    child = partners.create(
        {"name": _name("Cycle Child"), "parent_id": parent, "type": "contact"}
    )

    with pytest.raises(ValidationError):
        partners.write([parent], {"parent_id": child})
    with pytest.raises(ValidationError):
        partners.write([parent], {"parent_id": parent})

    partners.unlink([child, parent])


def test_hierarchical_tags_and_child_of_search(env, partners):
    tags = env["core.partner_tag"]
    parent_tag = tags.create({"name": _name("Tag Parent")})
    child_tag = tags.create({"name": _name("Tag Child"), "parent_id": parent_tag})
    outside_tag = tags.create({"name": _name("Other Tag")})
    company = partners.create({"name": _name("Tagged Co"), "is_company": True})
    partners.write([company], {"tag_ids": [child_tag]})

    assert partners.search([("tag_ids", "=", child_tag)]) == [company]
    assert company in partners.search([("tag_ids", "child_of", parent_tag)])
    assert company not in partners.search([("tag_ids", "child_of", outside_tag)])

    partners.unlink([company])
    tags.unlink([child_tag, parent_tag, outside_tag])


def test_industry_and_registry_delegate_to_contact_children(env, partners):
    industry_id = env["core.industry"].create({"name": _name("Industry")})
    company = partners.create(
        {
            "name": _name("Delegating Co"),
            "is_company": True,
            "industry_id": industry_id,
            "company_registry": "REG-1",
        }
    )
    person = partners.create(
        {"name": _name("Delegated Person"), "parent_id": company, "type": "contact"}
    )

    row = partners.read([person])[0]
    assert row["industry_id"]["id"] == industry_id
    assert row["company_registry"] == "REG-1"

    partners.unlink([person, company])
    env["core.industry"].unlink([industry_id])


def test_bank_account_is_normalised_and_unique_per_partner(env, partners):
    bank = env["core.bank"].create({"name": _name("Bank"), "bic": "eqbl kena"})
    assert env["core.bank"].read([bank])[0]["bic"] == "EQBLKENA"

    first = partners.create({"name": _name("Bank Co"), "is_company": True})
    second = partners.create({"name": _name("Other Bank Co"), "is_company": True})
    accounts = env["core.bank_account"]
    account = accounts.create(
        {"partner_id": first, "bank_id": bank, "acc_number": "0123-4567 8901"}
    )

    assert accounts.read([account])[0]["acc_number"] == "012345678901"
    with pytest.raises(ValidationError):
        accounts.create(
            {"partner_id": first, "bank_id": bank, "acc_number": "012345678901"}
        )
    allowed = accounts.create(
        {"partner_id": second, "bank_id": bank, "acc_number": "012345678901"}
    )

    accounts.unlink([allowed, account])
    partners.unlink([second, first])
    env["core.bank"].unlink([bank])


def test_delete_is_blocked_when_referenced(env, partners):
    bank = env["core.bank"].create({"name": _name("Delete Bank")})
    partner = partners.create({"name": _name("Delete Co"), "is_company": True})
    account = env["core.bank_account"].create(
        {"partner_id": partner, "bank_id": bank, "acc_number": "999"}
    )

    with pytest.raises(ValidationError):
        partners.unlink([partner])

    env["core.bank_account"].unlink([account])
    partners.unlink([partner])
    env["core.bank"].unlink([bank])


def test_archive_is_blocked_for_a_user_contact(env, partners):
    partner = partners.create({"name": _name("User Contact"), "is_company": False})
    user = env["core.user"].create(
        {
            "name": _name("Restricted User"),
            "login": f"c1-{uuid.uuid4().hex[:8]}",
            "partner_id": partner,
        }
    )

    with pytest.raises(ValidationError):
        partners.write([partner], {"active": False})

    env["core.user"].unlink([user])
    partners.unlink([partner])


def test_archived_contacts_are_hidden_by_default(partners):
    partner = partners.create({"name": _name("Archived Co"), "is_company": True})
    name = partners.read([partner])[0]["name"]
    partners.write([partner], {"active": False})

    assert partner not in partners.search([("name", "=", name)])
    assert partner in partners.search([("name", "=", name), ("active", "=", False)])

    partners.unlink([partner])


def test_address_get_prefers_the_right_level(partners):
    company = partners.create({"name": _name("Address Get Co"), "is_company": True})
    person = partners.create(
        {"name": _name("Address Get Person"), "parent_id": company, "type": "contact"}
    )
    invoice = partners.create(
        {"name": _name("Invoice Address"), "parent_id": company, "type": "invoice"}
    )
    delivery = partners.create(
        {"name": _name("Delivery Address"), "parent_id": company, "type": "delivery"}
    )

    assert partners.address_get(person) == {
        "contact": person,
        "invoice": invoice,
        "delivery": delivery,
        "other": company,
    }
    assert partners.address_get(company, ["contact", "invoice"]) == {
        "contact": company,
        "invoice": invoice,
    }
    assert partners.address_get(invoice, ["contact", "invoice"]) == {
        "contact": company,
        "invoice": invoice,
    }
    with pytest.raises(ValidationError):
        partners.address_get(person, ["billing"])

    partners.unlink([delivery, invoice, person, company])


def test_company_record_rule_limits_reads_and_writes(env, partners):
    from kberp.env import Env
    from kberp.orm.model import AccessError

    own_company = env["core.company"].search([], limit=1)[0]
    other_company = env["core.company"].create({"name": _name("Other Company")})
    own = partners.create(
        {"name": _name("Own Partner"), "is_company": True, "company_id": own_company}
    )
    foreign = partners.create(
        {"name": _name("Foreign Partner"), "is_company": True, "company_id": other_company}
    )
    shared = partners.create({"name": _name("Shared Partner"), "is_company": True})

    user = Env(
        env.db,
        registry=env.registry,
        uid=99,
        user={
            "id": 99,
            "login": "rule-user",
            "is_admin": False,
            "company_id": own_company,
            "group_xmlids": ["base.group_user", "base.group_partner_manager"],
        },
    )
    visible = user["core.partner"].search(
        [("id", "in", [own, foreign, shared])], order="id"
    )
    assert visible == [own, shared]
    assert user["core.partner"].read([foreign]) == []
    with pytest.raises(AccessError):
        user["core.partner"].write([foreign], {"name": _name("Renamed")})
    with pytest.raises(AccessError):
        user["core.partner"].create(
            {"name": _name("Sneaky"), "is_company": True, "company_id": other_company}
        )

    # The administrator is not filtered by record rules.
    assert env["core.partner"].search([("id", "=", foreign)]) == [foreign]

    partners.unlink([shared, foreign, own])
    env["core.company"].unlink([other_company])
