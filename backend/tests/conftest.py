"""
Shared pytest fixtures.

Sets a DEDICATED test database and disables the LLM before the app is
imported, so the test suite is fast, deterministic, and never depends on
network access or an API key — every test exercises the rule-based path,
which is exactly what should run in CI anyway.
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_coordination_engine.db"
os.environ["LLM_ENABLED"] = "False"
os.environ["MONITORING_ENABLED"] = "False"
os.environ["RATE_LIMIT_ENABLED"] = "False"
os.environ["JOB_QUEUE_ENABLED"] = "False"
os.environ["SLACK_WEBHOOK_URL"] = ""
os.environ["DISCORD_WEBHOOK_URL"] = ""
os.environ["TEAMS_WEBHOOK_URL"] = ""
os.environ["SMTP_HOST"] = ""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import engine, Base, AsyncSessionLocal
from app.services.seed_users import seed_demo_users
from app.services.workflow_orchestrator_service import seed_workflow_definitions

from app.models import dev_collab, incident, memory, tool_execution, monitoring, user, notification, enterprise, workflow, workflow_engine  # noqa: F401


@pytest_asyncio.fixture(autouse=True)
async def _reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await seed_demo_users()
    async with AsyncSessionLocal() as db:
        await seed_workflow_definitions(db)
    yield


@pytest.fixture(autouse=True)
def _stub_external_lookup(monkeypatch):
    from app.agents.aiops import external_lookup_agent

    async def _fake_find_related_issues(query, timeout=4.0, max_results=3):
        return []

    monkeypatch.setattr(
        external_lookup_agent.ExternalLookupAgent,
        "find_related_issues",
        staticmethod(_fake_find_related_issues),
    )


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post(
            "/api/auth/login",
            json={"email": "priya@infosys.com", "password": "demo123"},
        )
        if login.status_code == 200:
            ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield ac
