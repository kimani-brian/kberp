"""Parity checks: the committed menu fixture and referential view checks."""

from __future__ import annotations

from kberp.parity import check_menus, check_views, diff_menus, menu_snapshot


def test_menu_fixture_matches_database(env):
    check_menus(env)


def test_view_action_menu_references_are_sound(env):
    check_views(env)


def test_fixture_diff_reports_drift(env):
    snapshot = menu_snapshot(env)
    snapshot[0]["name"] = snapshot[0]["name"] + " (drifted)"
    problems = diff_menus(snapshot, {"menus": snapshot})
    assert problems == []  # self-comparison is clean

    expected = {"menus": [dict(item) for item in snapshot]}
    expected["menus"][0]["name"] = "Something else"
    problems = diff_menus(snapshot, expected)
    assert any(".name:" in problem for problem in problems)


def test_parity_scorecard_is_green(env):
    from kberp.parity import action_snapshot, check_parity, parity_report

    report = parity_report(env)
    assert report["ok"], report["problems"]
    assert report["menus"]["score"] == 100.0
    assert report["actions"]["score"] == 100.0
    assert len(report["actions"]) == 0 or report["actions"]["total"] == len(action_snapshot(env))
    assert [app["key"] for app in report["apps"]] == [
        "contacts",
        "sales",
        "accounting",
        "purchase",
        "inventory",
    ]
    assert all(app["menus"] for app in report["apps"])
    assert report["settings_groups"]
    check_parity(env)
