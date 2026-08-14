async def test_knowledge_base_grows_with_repeated_incidents(client):
    payload = {
        "service_name": "auth-service",
        "response_time_ms": 9000,
        "error_rate_pct": 80,
        "db_pool_usage_pct": 97,
        "affected_users_pct": 90,
    }
    await client.post("/api/incidents/ingest-metrics", json=payload)
    await client.post("/api/incidents/ingest-metrics", json=payload)

    kb = (await client.get("/api/system/knowledge-base")).json()
    assert len(kb) == 1
    assert kb[0]["success_count"] == 2
    assert kb[0]["category"] == "incident_resolution"


async def test_knowledge_base_separates_different_signatures(client):
    for service in ("auth-service", "checkout-service"):
        await client.post(
            "/api/incidents/ingest-metrics",
            json={
                "service_name": service,
                "response_time_ms": 9000,
                "error_rate_pct": 80,
                "db_pool_usage_pct": 97,
                "affected_users_pct": 90,
            },
        )

    kb = (await client.get("/api/system/knowledge-base")).json()
    assert len(kb) == 2


async def test_llm_failure_toggle_reflected_in_status(client):
    resp = await client.post("/api/system/toggle-llm-failure?enabled=true")
    assert resp.json()["simulated_llm_failure"] is True

    status = await client.get("/api/system/llm-failure-status")
    assert status.json()["simulated_llm_failure"] is True

    # Reset for any other test that might run after this in the same process.
    await client.post("/api/system/toggle-llm-failure?enabled=false")


async def test_stats_endpoint_reflects_activity(client):
    await client.post("/api/dev-collab/simulate-demo-conflict")
    await client.post(
        "/api/incidents/ingest-metrics",
        json={
            "service_name": "checkout-service",
            "response_time_ms": 9000,
            "error_rate_pct": 80,
            "db_pool_usage_pct": 97,
            "affected_users_pct": 90,
        },
    )

    stats = (await client.get("/api/system/stats")).json()
    assert stats["active_edit_sessions"] == 0
    assert stats["conflicts_predicted"] == 0

    incidents = (await client.get("/api/incidents/")).json()
    assert len(incidents) >= 1
