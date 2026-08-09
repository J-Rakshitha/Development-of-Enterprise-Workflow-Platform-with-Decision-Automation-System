"""Pre-deploy features: production simulate guard, monitored services, rate limits, job queue."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_app_config_endpoint(client):
    resp = await client.get("/api/system/app-config")
    assert resp.status_code == 200
    data = resp.json()
    assert "production" in data
    assert "simulate_enabled" in data
    assert data["simulate_enabled"] is True


@pytest.mark.asyncio
async def test_simulate_blocked_in_production(client, monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(cfg, "settings", cfg.Settings(ENV="production"))
    resp = await client.post("/api/dev-collab/simulate-demo-conflict")
    assert resp.status_code == 403
    resp2 = await client.post("/api/incidents/simulate")
    assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_admin_monitored_services_crud(client):
    login = await client.post(
        "/api/auth/login",
        json={"email": "admin@infosys.com", "password": "admin123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/admin/monitored-services",
        headers=headers,
        json={
            "name": "payment-service-test",
            "url": "https://httpbin.org/status/200",
            "enabled": True,
            "is_internal": False,
        },
    )
    assert create.status_code == 200
    svc_id = create.json()["id"]

    listed = await client.get("/api/admin/monitored-services", headers=headers)
    assert listed.status_code == 200
    names = {s["name"] for s in listed.json()}
    assert "payment-service-test" in names

    updated = await client.put(
        f"/api/admin/monitored-services/{svc_id}",
        headers=headers,
        json={"enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = await client.delete(f"/api/admin/monitored-services/{svc_id}", headers=headers)
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_login(monkeypatch):
    from app.core import config as cfg
    from app.middleware.rate_limit import RateLimitMiddleware

    monkeypatch.setattr(cfg, "settings", cfg.Settings(RATE_LIMIT_ENABLED=True, RATE_LIMIT_AUTH_PER_MINUTE=2))
    RateLimitMiddleware._hits.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(2):
            resp = await ac.post(
                "/api/auth/login",
                json={"email": "wrong@example.com", "password": "bad"},
            )
            assert resp.status_code in (401, 200)

        blocked = await ac.post(
            "/api/auth/login",
            json={"email": "wrong@example.com", "password": "bad"},
        )
        assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_job_queue_stats_in_app_config(client):
    resp = await client.get("/api/system/app-config")
    assert resp.status_code == 200
    assert "job_queue" in resp.json()
    assert resp.json()["job_queue"]["enabled"] is False
