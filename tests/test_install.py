"""Installer tests: installing twice must not duplicate or lose metadata."""

from __future__ import annotations

from kberp.installer import Installer

MODELS = (
    "core.ir_module",
    "core.ir_ui_menu",
    "core.ir_act_window",
    "core.ir_act_client",
    "core.ir_ui_view",
    "core.ir_model_access",
    "core.res_groups",
    "core.country",
    "core.currency",
    "core.uom",
    "core.product_category",
    "core.partner",
    "core.user",
    "platform.outbox_event",
    "core.ir_cron",
)


def _counts(env) -> dict[str, int]:
    return {model: env[model].search_count([]) for model in MODELS}


def test_init_is_idempotent(settings, env):
    before = _counts(env)
    summary = Installer(settings).init(demo=True)
    after = _counts(env)

    assert summary["models"] == len(env.registry.models)
    assert summary["modules"] == [
        "base",
        "contacts",
        "accounting",
        "inventory",
        "sales",
        "purchase",
    ]
    assert after == before
    assert after["core.ir_ui_menu"] == 202


def test_modules_and_admin_are_recorded(env):
    modules = env["core.ir_module"].search([], order="name")
    names = [row["name"] for row in env["core.ir_module"].read(modules)]
    assert names == ["accounting", "base", "contacts", "inventory", "purchase", "sales"]
    admin = env["core.user"].search([("login", "=", "admin")], limit=1)
    assert admin
    user = env["core.user"].read(admin)[0]
    assert user["is_admin"] is True
    assert "base.group_system" in user["group_xmlids"]
