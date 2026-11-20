"""Test fixtures: a throwaway database, an initialised registry and a web client."""

from __future__ import annotations

import dataclasses
import re

import psycopg
import pytest
from werkzeug.test import Client

from kberp.config import Settings
from kberp.db import Database
from kberp.env import Env
from kberp.installer import Installer
from kberp.registry import Registry
from kberp.web.app import create_app

TEST_DB = "kberp_test_ci"


def _admin_conninfo(settings: Settings) -> str:
    return (
        f"host={settings.db_host} port={settings.db_port} dbname=postgres "
        f"user={settings.db_user} password={settings.db_password}"
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    base = Settings.from_env()
    with psycopg.connect(_admin_conninfo(base), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    test_settings = dataclasses.replace(base, db_name=TEST_DB)
    Installer(test_settings).init(demo=True, fresh=True)
    return test_settings


@pytest.fixture(scope="session")
def registry(settings: Settings) -> Registry:
    registry = Registry(settings)
    registry.load()
    return registry


@pytest.fixture()
def db(settings: Settings):
    database = Database(settings)
    database.open()
    yield database
    database.close()


@pytest.fixture()
def env(db, registry) -> Env:
    return Env(db, registry=registry, su=True)


@pytest.fixture(scope="session")
def app(settings: Settings):
    application = create_app(settings)
    application.db.open()
    yield application
    application.db.close()


@pytest.fixture()
def client(app) -> Client:
    return Client(app)


def login(client: Client, login_name: str = "admin", password: str = "admin"):
    page = client.get("/web/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    assert token, "login form has no CSRF token"
    response = client.post(
        "/web/login",
        data={"csrf_token": token.group(1), "login": login_name, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.get_data(as_text=True)
    return client


def csrf_from(client: Client, path: str) -> str:
    page = client.get(path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    assert match, f"no CSRF token on {path}"
    return match.group(1)


def action_id(env: Env, xml_id: str) -> int:
    ids = env["core.ir_act_window"].search([("xml_id", "=", xml_id)], limit=1)
    assert ids, f"action {xml_id} not found"
    return ids[0]
