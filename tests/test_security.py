"""Security baseline: ACL coverage, hashing and production defaults."""

from __future__ import annotations

import dataclasses

from kberp.security import (
    constant_time_equals,
    hash_password,
    new_csrf_token,
    new_session_token,
    verify_password,
)
from kberp.security_audit import (
    audit,
    check_security,
    missing_access,
    production_settings_findings,
)


def test_every_model_has_an_access_rule(env):
    assert missing_access(env) == []


def test_security_audit_is_clean(env, settings):
    report = audit(env, settings)
    assert report["ok"], report["findings"]
    assert report["findings"] == []
    assert report["models"] > 100
    assert report["access_rules"] > report["models"]
    check_security(env, settings)


def test_production_defaults_are_flagged(settings):
    production = dataclasses.replace(
        settings,
        debug=False,
        secret_key="dev-secret",
        admin_password="admin",
        db_password="kberp",
    )
    codes = {item.code for item in production_settings_findings(production)}
    assert codes == {"secret-key", "admin-password", "db-password"}

    hardened = dataclasses.replace(
        settings,
        debug=False,
        secret_key="x" * 40,
        admin_password="correct-horse-battery",
        db_password="p" * 20,
    )
    assert production_settings_findings(hardened) == []


def test_password_hashing_round_trip():
    stored = hash_password("s3cret-passphrase")
    assert stored.startswith("$argon2id$")
    assert stored != "s3cret-passphrase"
    assert verify_password(stored, "s3cret-passphrase")
    assert not verify_password(stored, "wrong")
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "anything")


def test_tokens_are_unique_and_compare_safely():
    assert new_session_token() != new_session_token()
    assert new_csrf_token() != new_csrf_token()
    assert len(new_session_token()) >= 40
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")
