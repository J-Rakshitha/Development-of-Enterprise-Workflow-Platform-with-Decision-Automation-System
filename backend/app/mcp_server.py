"""
MCP Server — Phase D: Industry-standard tool exposure
========================================================
Exposes the same enterprise tools from TOOL_REGISTRY via Model Context Protocol,
so external AI clients (Cursor, Claude Desktop) can invoke them.

Run standalone:
    cd backend && python -m app.mcp_server

Or configure in Cursor ~/.cursor/mcp.json (see README).
"""
import json

from mcp.server.fastmcp import FastMCP

from app.core.database import AsyncSessionLocal
from app.agents.tools import tool_handlers  # noqa: F401 — populates registry
from app.agents.tools.tool_registry import list_tools_public
from app.agents.tools.tool_executor_agent import ToolExecutorAgent
from app.agents.aiops.server_monitor_agent import ServerMonitorAgent
from app.services.monitoring_scheduler import get_monitor_targets
from app.core.config import settings

mcp = FastMCP(
    "Development of Enterprise Workflow Platform with Decision Automation System",
    instructions=(
        "Enterprise multi-agent coordination engine for Dev-Collaboration "
        "conflict prevention and AIOps incident response. Tools mirror the "
        "REST /api/tools registry plus monitoring and GitHub sync."
    ),
)


async def _with_db(coro_factory):
    async with AsyncSessionLocal() as db:
        return await coro_factory(db)


@mcp.tool()
async def list_available_tools() -> str:
    """List all registered enterprise tools with descriptions."""
    return json.dumps(list_tools_public(), indent=2)


@mcp.tool()
async def github_issue_lookup(query: str) -> str:
    """Search GitHub's public issue tracker for reports matching an error pattern."""
    from app.agents.tools.tool_handlers import handler_github_issue_lookup
    result = await _with_db(lambda db: handler_github_issue_lookup(db, query=query))
    return json.dumps(result, default=str)


@mcp.tool()
async def create_escalation_ticket(incident_id: int, severity: str = "P2", reason: str = "") -> str:
    """Create an enterprise ITSM escalation ticket with SLA deadline."""
    from app.agents.tools.tool_handlers import handler_create_escalation_ticket
    result = await _with_db(
        lambda db: handler_create_escalation_ticket(db, incident_id=incident_id, severity=severity, reason=reason)
    )
    return json.dumps(result, default=str)


@mcp.tool()
async def query_knowledge_base(key_signature: str) -> str:
    """Look up long-term agent memory for a previously-seen pattern."""
    from app.agents.tools.tool_handlers import handler_query_knowledge_base
    result = await _with_db(lambda db: handler_query_knowledge_base(db, key_signature=key_signature))
    return json.dumps(result, default=str)


@mcp.tool()
async def restart_service(incident_id: int | None = None) -> str:
    """Restart the affected service — fixes connection pool / timeout issues."""
    from app.agents.tools.tool_handlers import handler_restart_service
    result = await _with_db(lambda db: handler_restart_service(db, incident_id=incident_id))
    return json.dumps(result, default=str)


@mcp.tool()
async def clear_cache(incident_id: int | None = None) -> str:
    """Clear the affected service cache — fixes stale-data issues."""
    from app.agents.tools.tool_handlers import handler_clear_cache
    result = await _with_db(lambda db: handler_clear_cache(db, incident_id=incident_id))
    return json.dumps(result, default=str)


@mcp.tool()
async def select_and_execute_tool(situation: str, incident_id: int | None = None) -> str:
    """Intelligently select and execute the best tool for a natural-language situation."""
    async def _run(db):
        return await ToolExecutorAgent.select_and_execute(db, situation, incident_id=incident_id)
    result = await _with_db(_run)
    return json.dumps(result, default=str)


@mcp.tool()
async def check_service_health(service_name: str | None = None) -> str:
    """Run a live HTTP health probe on monitored services (real, not simulated)."""
    targets = get_monitor_targets()
    if service_name:
        targets = [t for t in targets if t["name"] == service_name]
    results = []
    for t in targets:
        probe = await ServerMonitorAgent.probe(t["name"], t["url"])
        results.append(probe)
    return json.dumps(results, default=str)


@mcp.tool()
async def sync_github_conflicts() -> str:
    """Fetch live open PRs, rebuild Live Editing Map, and detect real conflicts."""
    from app.services.github_sync_service import run_github_sync

    async def _sync(db):
        return await run_github_sync(db, trigger="mcp")

    result = await _with_db(_sync)
    return json.dumps(result, default=str)


@mcp.tool()
async def list_open_prs() -> str:
    """List open pull requests from the configured GitHub repository."""
    from app.agents.tools.tool_handlers import handler_list_open_prs
    result = await _with_db(lambda db: handler_list_open_prs(db))
    return json.dumps(result, default=str)


@mcp.tool()
async def get_pr_diff(pr_number: int) -> str:
    """Fetch file-level diff summary for a GitHub pull request."""
    from app.agents.tools.tool_handlers import handler_get_pr_diff
    result = await _with_db(lambda db: handler_get_pr_diff(db, pr_number=pr_number))
    return json.dumps(result, default=str)


@mcp.tool()
async def sync_github_repo_full() -> str:
    """Full GitHub sync — live map + conflict detection."""
    from app.services.github_sync_service import run_github_sync

    async def _run(db):
        return await run_github_sync(db, trigger="mcp")

    result = await _with_db(_run)
    return json.dumps(result, default=str)


@mcp.resource("config://monitor-targets")
def monitor_targets_resource() -> str:
    """Configured real-time monitoring targets (backend + external)."""
    return json.dumps({
        "monitoring_enabled": settings.MONITORING_ENABLED,
        "interval_seconds": settings.MONITOR_INTERVAL_SECONDS,
        "targets": get_monitor_targets(),
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
