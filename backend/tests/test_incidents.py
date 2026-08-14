async def test_simulate_incident_runs_full_pipeline(client):
    resp = await client.post("/api/incidents/simulate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["anomaly_detected"] is True
    assert body["severity"] in ("P1", "P2", "P3")
    assert body["root_cause"]
    assert body["action_taken"]

    listed = (await client.get("/api/incidents/")).json()
    assert len(listed) == 0


async def test_ingest_metrics_healthy_service_no_incident(client):
    payload = {
        "service_name": "checkout-service",
        "response_time_ms": 120,
        "error_rate_pct": 1,
        "db_pool_usage_pct": 20,
        "affected_users_pct": 0,
    }
    resp = await client.post("/api/incidents/ingest-metrics", json=payload)
    assert resp.status_code == 200
    assert resp.json()["anomaly_detected"] is False

    listed = (await client.get("/api/incidents/")).json()
    assert len(listed) == 0


async def test_ingest_metrics_severe_anomaly_triggers_p1(client):
    payload = {
        "service_name": "checkout-service",
        "response_time_ms": 9000,
        "error_rate_pct": 80,
        "db_pool_usage_pct": 97,
        "affected_users_pct": 90,
    }
    resp = await client.post("/api/incidents/ingest-metrics", json=payload)
    body = resp.json()
    assert body["anomaly_detected"] is True
    assert body["severity"] == "P1"
    assert body["status"] in ("auto_resolved", "escalated")


async def test_incident_response_includes_expected_fields(client):
    resp = await client.post("/api/incidents/simulate")
    body = resp.json()
    for field in ("incident_id", "severity", "root_cause", "action_taken", "status", "external_references"):
        assert field in body
