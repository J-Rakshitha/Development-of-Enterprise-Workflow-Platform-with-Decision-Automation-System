"""Enterprise 5-phase intelligence — discovery, semantic, synthesizer, quality, RAG."""
import json

import pytest


@pytest.mark.asyncio
async def test_repository_discovery(client):
    res = await client.post("/api/dev-collab/repository/discovery")
    assert res.status_code == 200
    data = res.json()
    assert data["context"]["symbols_indexed"] > 0
    assert data["context"]["scan_source"] == "local_ast"


@pytest.mark.asyncio
async def test_simulate_conflict_runs_enterprise_pipeline(client):
    res = await client.post("/api/dev-collab/simulate-demo-conflict")
    assert res.status_code == 200
    conflict_id = res.json()["conflict_id"]

    from app.core.database import AsyncSessionLocal
    from app.models.dev_collab import ConflictEvent
    import json

    async with AsyncSessionLocal() as db:
        row = await db.get(ConflictEvent, conflict_id)
        assert row.discovery_context is not None
        assert row.semantic_analysis is not None
        assert row.quality_report is not None
        assert row.code_review_notes is not None
        semantic = json.loads(row.semantic_analysis)
        quality = json.loads(row.quality_report)
        assert semantic["semantic_risk_score"] >= 0
        assert quality["grade"] in ("A", "B", "C")

    conflicts = await client.get("/api/dev-collab/conflicts")
    assert conflicts.status_code == 200
    assert not any(c["id"] == conflict_id for c in conflicts.json())


@pytest.mark.asyncio
async def test_suggest_resolution_includes_synthesizer(client):
    sim = await client.post("/api/dev-collab/simulate-demo-conflict")
    conflict_id = sim.json()["conflict_id"]

    res = await client.post(f"/api/dev-collab/conflicts/{conflict_id}/suggest-resolution")
    assert res.status_code == 200
    data = res.json()
    assert "synthesizer" in data
    assert len(data["synthesizer"]["options"]) == 3
    assert data["synthesizer"]["best_strategy"]["strategy"] in (
        "rebase_and_merge",
        "feature_branch_split",
        "pair_programming_sync",
    )


@pytest.mark.asyncio
async def test_knowledge_base_semantic_search(client):
    await client.post("/api/dev-collab/simulate-demo-conflict")
    res = await client.get("/api/system/knowledge-base/search", params={"q": "conflict merge resolution"})
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    assert data["query"] == "conflict merge resolution"


@pytest.mark.asyncio
async def test_enterprise_tools_registered(client):
    res = await client.get("/api/tools/")
    assert res.status_code == 200
    names = {t["name"] for t in res.json()}
    assert "semantic_conflict_analyze" in names
    assert "evaluate_code_quality" in names
    assert "semantic_knowledge_search" in names


@pytest.mark.asyncio
async def test_semantic_tool_execute(client):
    res = await client.post(
        "/api/tools/select-and-execute",
        json={
            "situation": "Two developers have a semantic merge conflict in auth.py login function",
            "module": "dev_collab",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("success") is True or body.get("tool_name") in (
        "semantic_conflict_analyze",
        "evaluate_code_quality",
        "semantic_knowledge_search",
        "query_knowledge_base",
    )
