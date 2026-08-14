"""Enterprise AIOps — observability webhook and incident source tracking."""
import json

import pytest


@pytest.mark.asyncio
async def test_observability_status(client):
    resp = await client.get("/api/incidents/observability/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "webhook_url" in body
    assert body["webhook_url"].endswith("/api/incidents/alert-webhook")
    assert "webhook_secret_configured" in body
    assert "monitoring_enabled" in body
    assert "registered_services" in body


@pytest.mark.asyncio
async def test_alert_webhook_creates_real_incident(client, monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "METRICS_WEBHOOK_SECRET", "test-metrics-secret")

    payload = {
        "service_name": "checkout-service",
        "response_time_ms": 9000,
        "error_rate_pct": 80,
        "db_pool_usage_pct": 95,
        "affected_users_pct": 85,
    }
    resp = await client.post(
        "/api/incidents/alert-webhook",
        content=json.dumps(payload),
        headers={
            "Content-Type": "application/json",
            "X-Metrics-Webhook-Secret": "test-metrics-secret",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] is True
    assert body["anomaly_detected"] is True
    assert body["source"] == "webhook"

    listed = (await client.get("/api/incidents/")).json()
    assert any(i["id"] == body["incident_id"] for i in listed)
    row = next(i for i in listed if i["id"] == body["incident_id"])
    assert row["source"] == "webhook"
    assert row["triggered_by"] == "Grafana Alert"


@pytest.mark.asyncio
async def test_alert_webhook_rejects_bad_secret(client, monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "METRICS_WEBHOOK_SECRET", "test-metrics-secret")
    monkeypatch.setattr(cfg.settings, "ENV", "production")

    resp = await client.post(
        "/api/incidents/alert-webhook",
        content=json.dumps({"service_name": "x", "response_time_ms": 9000, "error_rate_pct": 80, "db_pool_usage_pct": 90, "affected_users_pct": 80}),
        headers={"Content-Type": "application/json", "X-Metrics-Webhook-Secret": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_creates_visible_ops_notification(client):
    # Admin is not a DEMO_DEV_NAMES seed developer — ops card stays visible in Team Notifications
    login = await client.post(
        "/api/auth/login",
        json={"email": "admin@infosys.com", "password": "admin123"},
    )
    assert login.status_code == 200
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    payload = {
        "service_name": "checkout-service",
        "response_time_ms": 9000,
        "error_rate_pct": 80,
        "db_pool_usage_pct": 97,
        "affected_users_pct": 90,
    }
    resp = await client.post("/api/incidents/ingest-metrics", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["anomaly_detected"] is True
    assert body["source"] == "ingest"
    assert body["triggered_by"] == "Admin User"

    listed = (await client.get("/api/incidents/")).json()
    assert listed[0]["source"] == "ingest"
    assert listed[0]["triggered_by"] == "Admin User"

    notifications = (await client.get("/api/system/notifications")).json()
    ops = [n for n in notifications if str(n.get("recipient", "")).startswith("ops:")]
    assert len(ops) >= 1
    assert ops[0]["event_type"] == "incident_created"
    assert "Admin" in ops[0]["recipient"]
    assert not any("Priya" in str(n.get("recipient", "")) for n in ops)


@pytest.mark.asyncio
async def test_repeated_ingest_keeps_history_cards(client):
    """Each Send Real Test Metrics click creates a new card — no upsert override."""
    payload = {
        "service_name": "auth-service",
        "response_time_ms": 9000,
        "error_rate_pct": 80,
        "db_pool_usage_pct": 97,
        "affected_users_pct": 90,
    }
    first = (await client.post("/api/incidents/ingest-metrics", json=payload)).json()
    second = (await client.post("/api/incidents/ingest-metrics", json={
        **payload,
        "service_name": "payment-service",
        "error_rate_pct": 55,
        "db_pool_usage_pct": 88,
    })).json()
    assert first["anomaly_detected"] and second["anomaly_detected"]
    assert first["incident_id"] != second["incident_id"]

    listed = (await client.get("/api/incidents/")).json()
    ids = {i["id"] for i in listed}
    assert first["incident_id"] in ids
    assert second["incident_id"] in ids
    mine = [i for i in listed if i["triggered_by"] == "Priya Sharma"]
    assert len(mine) >= 2


@pytest.mark.asyncio
async def test_simulate_incident_hidden_from_list(client):
    resp = await client.post("/api/incidents/simulate")
    assert resp.status_code == 200
    assert resp.json()["source"] == "simulate"

    listed = (await client.get("/api/incidents/")).json()
    assert not any(i.get("source") == "simulate" for i in listed)


def test_metrics_webhook_normalize_direct():
    from app.services.metrics_webhook_service import MetricsWebhookService

    out = MetricsWebhookService.normalize_metrics({
        "service_name": "payment-service",
        "response_time_ms": 5000,
        "error_rate_pct": 70,
        "db_pool_usage_pct": 88,
        "affected_users_pct": 60,
    })
    assert out["service_name"] == "payment-service"
    assert out["error_rate_pct"] == 70.0


def test_metrics_webhook_normalize_grafana():
    from app.services.metrics_webhook_service import MetricsWebhookService

    out = MetricsWebhookService.normalize_metrics({
        "alerts": [{
            "status": "firing",
            "labels": {"service_name": "checkout-service"},
            "annotations": {"summary": "High error rate detected"},
        }],
    })
    assert out["service_name"] == "checkout-service"
    assert out["error_rate_pct"] >= 60
