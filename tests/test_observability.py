"""Observability: request IDs, metrics exposition and scrape protection."""

from __future__ import annotations

import dataclasses

from werkzeug.test import Client

from kberp.web.app import create_app


def test_request_id_is_generated_and_echoed(client):
    first = client.get("/healthz")
    assert first.headers["X-Request-ID"]
    second = client.get("/healthz", headers={"X-Request-ID": "uat-request-123"})
    assert second.headers["X-Request-ID"] == "uat-request-123"


def test_metrics_exposes_http_and_outbox_gauges(client):
    client.get("/healthz")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    body = response.get_data(as_text=True)
    assert "kberp_http_requests_total{" in body
    assert 'endpoint="healthz"' in body
    assert "kberp_http_request_duration_seconds_bucket{" in body
    assert "kberp_outbox_pending_events" in body
    assert "kberp_database_up 1.0" in body


def test_metrics_requires_bearer_token_when_configured(settings):
    secured = dataclasses.replace(settings, debug=False, metrics_token="s3cret-token")
    app = create_app(secured)
    app.db.open()
    try:
        client = Client(app)
        assert client.get("/metrics").status_code == 403
        assert (
            client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code
            == 403
        )
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer s3cret-token"}
        )
        assert response.status_code == 200
        assert "kberp_models" in response.get_data(as_text=True)
    finally:
        app.db.close()


def test_metrics_closed_in_production_without_token(settings):
    secured = dataclasses.replace(settings, debug=False, metrics_token="")
    app = create_app(secured)
    app.db.open()
    try:
        assert Client(app).get("/metrics").status_code == 403
    finally:
        app.db.close()
