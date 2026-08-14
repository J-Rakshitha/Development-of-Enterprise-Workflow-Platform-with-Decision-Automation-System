"""Milestone 3 — Agent Coordination & Memory Systems validation tests."""


async def test_cross_module_coordination_links_incident_to_commit(client):
    """
    Dev-Collab resolves a conflict on checkout.py → CommitLog is created.
    AIOps incident on checkout-service → Coordinator links them cross-module.
    """
    file_path = "checkout.py"
    function_name = "processPayment"

    await client.post(
        "/api/dev-collab/edit-session/start",
        json={"developer_name": "Priya Sharma", "file_path": file_path, "function_name": function_name},
    )
    await client.post(
        "/api/dev-collab/edit-session/start",
        json={"developer_name": "Arjun Mehta", "file_path": file_path, "function_name": function_name},
    )
    conflicts_resp = await client.post("/api/dev-collab/check-conflicts")
    assert conflicts_resp.json()["conflicts_found"] == 1
    conflict_id = conflicts_resp.json()["events"][0]

    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/suggest-resolution")
    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/approve")

    incident_resp = await client.post(
        "/api/incidents/ingest-metrics",
        json={
            "service_name": "checkout-service",
            "response_time_ms": 9000,
            "error_rate_pct": 80,
            "db_pool_usage_pct": 97,
            "affected_users_pct": 90,
        },
    )
    body = incident_resp.json()
    assert body["anomaly_detected"] is True
    assert body["linked_commit"] is not None
    assert body["linked_commit"]["file_path"] == file_path
    assert body["linked_commit"]["had_conflict"] is True


async def test_no_weak_link_without_service_file_match(client):
    """Unrelated conflict commit must NOT attach to payment-service (strict match only)."""
    file_path = "App.jsx"
    function_name = "Header"

    await client.post(
        "/api/dev-collab/edit-session/start",
        json={"developer_name": "Priya Sharma", "file_path": file_path, "function_name": function_name},
    )
    await client.post(
        "/api/dev-collab/edit-session/start",
        json={"developer_name": "Arjun Mehta", "file_path": file_path, "function_name": function_name},
    )
    conflicts_resp = await client.post("/api/dev-collab/check-conflicts")
    assert conflicts_resp.json()["conflicts_found"] == 1
    conflict_id = conflicts_resp.json()["events"][0]
    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/suggest-resolution")
    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/approve")

    incident_resp = await client.post(
        "/api/incidents/ingest-metrics",
        json={
            "service_name": "payment-service",
            "response_time_ms": 9000,
            "error_rate_pct": 80,
            "db_pool_usage_pct": 97,
            "affected_users_pct": 90,
        },
    )
    body = incident_resp.json()
    assert body["anomaly_detected"] is True
    assert body.get("linked_commit") is None


async def test_decision_log_records_both_modules(client):
    """Every agent step across Dev-Collab and AIOps appears in the explainable-AI trail."""
    sim = await client.post("/api/dev-collab/simulate-demo-conflict")
    conflict_id = sim.json()["conflict_id"]
    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/suggest-resolution")
    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/approve")
    await client.post("/api/incidents/simulate")

    logs = (await client.get("/api/system/decision-log")).json()
    modules = {entry["module"] for entry in logs}
    assert "dev_collab" in modules
    assert "aiops" in modules

    agent_names = {entry["agent_name"] for entry in logs}
    assert "Conflict Prediction Agent" in agent_names
    assert "Code Review Agent" in agent_names
    assert "Notification Agent" in agent_names
    assert "Resolution Suggestion Agent" in agent_names
    assert "Monitoring Agent" in agent_names
    assert "Root-Cause Analysis Agent" in agent_names
    assert "Severity Agent" in agent_names
    assert "Tool Selector Agent" in agent_names
    assert "Tool Executor Agent" in agent_names


async def test_short_term_memory_builds_across_incidents(client):
    """Repeated incidents reinforce long-term memory and populate short-term decision context."""
    payload = {
        "service_name": "auth-service",
        "response_time_ms": 9000,
        "error_rate_pct": 80,
        "db_pool_usage_pct": 97,
        "affected_users_pct": 90,
    }
    await client.post("/api/incidents/ingest-metrics", json=payload)
    await client.post("/api/incidents/ingest-metrics", json=payload)

    logs = (await client.get("/api/system/decision-log")).json()
    aiops_logs = [l for l in logs if l["module"] == "aiops"]
    assert len(aiops_logs) >= 2

    kb = (await client.get("/api/system/knowledge-base")).json()
    auth_entries = [e for e in kb if e["key_signature"].startswith("auth-service:")]
    assert len(auth_entries) == 1
    assert auth_entries[0]["success_count"] == 2


async def test_conflict_resolution_uses_long_term_memory(client):
    """Same file/function collision twice — knowledge base success_count increments."""
    file_path = "payment_service.py"
    function_name = "validateLogin"

    async def run_conflict_cycle():
        await client.post(
            "/api/dev-collab/edit-session/start",
            json={"developer_name": "Priya Sharma", "file_path": file_path, "function_name": function_name},
        )
        await client.post(
            "/api/dev-collab/edit-session/start",
            json={"developer_name": "Sneha Reddy", "file_path": file_path, "function_name": function_name},
        )
        conflicts = await client.post("/api/dev-collab/check-conflicts")
        conflict_id = conflicts.json()["events"][0]
        await client.post(f"/api/dev-collab/conflicts/{conflict_id}/suggest-resolution")
        await client.post(f"/api/dev-collab/conflicts/{conflict_id}/approve")
        sessions = (await client.get("/api/dev-collab/active-sessions")).json()
        for session in sessions:
            await client.post(f"/api/dev-collab/edit-session/{session['session_id']}/end")

    await run_conflict_cycle()
    await run_conflict_cycle()

    kb = (await client.get("/api/system/knowledge-base")).json()
    pattern = [e for e in kb if e["key_signature"] == f"{file_path}:{function_name}"]
    assert len(pattern) == 1
    assert pattern[0]["success_count"] >= 2
    assert pattern[0]["category"] == "conflict_pattern"


async def test_code_review_agent_runs_on_conflict_detection(client):
    """Detector → Code Review pipeline: conflict gets code_review_notes in DB."""
    sim = await client.post("/api/dev-collab/simulate-demo-conflict")
    assert sim.status_code == 200
    conflict_id = sim.json()["conflict_id"]

    from app.core.database import AsyncSessionLocal
    from app.models.dev_collab import ConflictEvent

    async with AsyncSessionLocal() as db:
        row = await db.get(ConflictEvent, conflict_id)
        assert row.code_review_notes
        assert len(row.code_review_notes) > 20

    conflicts = (await client.get("/api/dev-collab/conflicts")).json()
    assert len(conflicts) == 0


async def test_notification_agent_persists_team_alerts(client):
    """Notification Agent persists alerts; demo @infosys.com hidden from dashboard API."""
    sim = await client.post("/api/dev-collab/simulate-demo-conflict")
    conflict_id = sim.json()["conflict_id"]
    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/suggest-resolution")
    await client.post(f"/api/dev-collab/conflicts/{conflict_id}/approve")
    await client.post("/api/incidents/simulate")

    notifications = (await client.get("/api/system/notifications")).json()
    assert all(not n["recipient"].endswith("@infosys.com") for n in notifications)

    from app.core.database import AsyncSessionLocal
    from app.agents.notification_agent import NotificationAgent

    async with AsyncSessionLocal() as db:
        all_entries = await NotificationAgent.list_recent(db, limit=50)
    assert len(all_entries) >= 3
