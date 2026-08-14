"""Milestone 4 — Workflow orchestration and monitoring dashboard tests."""
import pytest


@pytest.mark.asyncio
async def test_workflow_definitions(client):
    resp = await client.get("/api/workflows/definitions")
    assert resp.status_code == 200
    defs = resp.json()
    assert len(defs) >= 3
    keys = {d["template_key"] for d in defs}
    assert "dev-conflict-resolution" in keys
    assert "incident-response" in keys
    assert "full-sdlc-bridge" in keys


@pytest.mark.asyncio
async def test_start_incident_response_workflow(client):
    resp = await client.post(
        "/api/workflows/start",
        json={"template_key": "incident-response", "context": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["template_key"] == "incident-response"
    assert data["status"] in ("completed", "running", "failed")
    assert data["incident_id"] or data["status"] == "completed"


@pytest.mark.asyncio
async def test_dev_conflict_workflow_hitl_pause_and_resume(client):
    sim = await client.post("/api/dev-collab/simulate-demo-conflict", timeout=60.0)
    assert sim.status_code == 200
    conflict_id = sim.json()["conflict_id"]

    start = await client.post(
        "/api/workflows/start",
        json={"template_key": "dev-conflict-resolution", "context": {"conflict_id": conflict_id}},
        timeout=60.0,
    )
    assert start.status_code == 200
    run = start.json()
    assert run["status"] == "waiting_hitl"
    run_id = run["id"]

    timeline = await client.get(f"/api/workflows/runs/{run_id}/timeline")
    assert timeline.status_code == 200
    steps = timeline.json()
    assert any(s["step_id"] == "hitl_gate" for s in steps)

    resume = await client.post(f"/api/workflows/runs/{run_id}/resume", timeout=60.0)
    assert resume.status_code == 200
    assert resume.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_workflow_stats(client):
    resp = await client.get("/api/workflows/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_runs" in data
    assert "completed" in data


@pytest.mark.asyncio
async def test_agent_metrics(client):
    await client.post("/api/incidents/simulate", timeout=60.0)
    resp = await client.get("/api/system/agent-metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_decisions"] >= 1
    assert isinstance(data["agents"], list)


@pytest.mark.asyncio
async def test_monitoring_summary(client):
    resp = await client.get("/api/monitoring/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "services" in data
    assert len(data["services"]) >= 2


@pytest.mark.asyncio
async def test_admin_system_health(client):
    login = await client.post(
        "/api/auth/login",
        json={"email": "admin@infosys.com", "password": "admin123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    resp = await client.get(
        "/api/admin/system-health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["database"] == "connected"
    assert "workflow_runs_total" in data


@pytest.mark.asyncio
async def test_admin_forbidden_for_developer(client):
    resp = await client.get("/api/admin/system-health")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_workflow_runs(client):
    resp = await client.get("/api/workflows/runs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
