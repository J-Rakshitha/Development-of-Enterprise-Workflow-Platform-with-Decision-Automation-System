"""
Tool Handlers — the actual API connectors registered into the Tool Registry.

Each handler is an async function with signature `(db, **kwargs) -> dict`
returning at minimum `{"success": bool, "output": ...}`. Handlers must
never raise for "expected" failure modes (they should catch and return
success=False) — the Tool Executor also wraps every call in a try/except
as a second safety net, so a badly-behaved handler still can't crash a
pipeline or a live demo.
"""
from app.agents.aiops.external_lookup_agent import ExternalLookupAgent
from app.agents.aiops.escalation_agent import EscalationAgent
from app.agents.aiops.remediation_agent import RemediationAgent, ACTION_LABELS
from app.agents.memory_agent import MemoryAgent
from app.agents.tools.tool_registry import Tool, register_tool


async def handler_github_issue_lookup(db, query: str = "", **kwargs) -> dict:
    """Real external API connector: GitHub public Issue Search."""
    results = await ExternalLookupAgent.find_related_issues(query or "incident")
    return {"success": True, "output": results}


async def handler_create_escalation_ticket(db, incident_id: int = 0, severity: str = "P2",
                                            reason: str = "", **kwargs) -> dict:
    """Enterprise ITSM-style connector: creates an escalation ticket with an SLA."""
    ticket = EscalationAgent.build_escalation(incident_id, severity, reason)
    return {"success": True, "output": ticket}


async def handler_query_knowledge_base(db, key_signature: str = "", **kwargs) -> dict:
    """Internal enterprise data source connector: the long-term memory store."""
    entry = await MemoryAgent.recall_knowledge(db, key_signature)
    if entry:
        return {"success": True, "output": entry.insight}
    return {"success": False, "output": "No matching knowledge base entry found."}


async def handler_restart_service(db, incident_id: int | None = None, **kwargs) -> dict:
    """Runbook-automation connector: restarts the affected service."""
    if incident_id:
        action = await RemediationAgent.perform_action(db, incident_id, "restart_service")
        return {"success": action.success, "output": action.notes}
    return {"success": True, "output": ACTION_LABELS["restart_service"] + " (simulated, no incident attached)"}


async def handler_clear_cache(db, incident_id: int | None = None, **kwargs) -> dict:
    """Runbook-automation connector: clears the affected service's cache."""
    if incident_id:
        action = await RemediationAgent.perform_action(db, incident_id, "clear_cache")
        return {"success": action.success, "output": action.notes}
    return {"success": True, "output": ACTION_LABELS["clear_cache"] + " (simulated, no incident attached)"}


async def handler_semantic_conflict_analyze(
    db,
    file_path: str = "",
    function_name: str = "",
    dev_a_name: str = "Dev A",
    dev_b_name: str = "Dev B",
    risk_score: float = 50.0,
    **kwargs,
) -> dict:
    """AST + LLM semantic conflict analysis for overlapping edits."""
    from app.agents.dev_collab.semantic_analysis_agent import SemanticAnalysisAgent

    result = await SemanticAnalysisAgent.analyze(
        db, file_path, function_name or None, dev_a_name, dev_b_name, risk_score
    )
    return {"success": True, "output": result}


async def handler_evaluate_code_quality(
    db,
    file_path: str = "",
    function_name: str = "",
    risk_score: float = 50.0,
    **kwargs,
) -> dict:
    """Structured quality scorecard from AST metrics."""
    from app.agents.dev_collab.quality_agent import QualityAgent

    result = await QualityAgent.evaluate(db, file_path, function_name or None, risk_score)
    return {"success": True, "output": result}


async def handler_semantic_knowledge_search(db, query: str = "", **kwargs) -> dict:
    """RAG semantic search over knowledge base and agent decisions."""
    from app.agents.dev_collab.knowledge_search_agent import KnowledgeSearchAgent

    result = await KnowledgeSearchAgent.search(db, query or "conflict resolution")
    return {"success": True, "output": result}


async def handler_list_open_prs(db, **kwargs) -> dict:
    """List open pull requests from the configured GitHub repository."""
    from app.agents.dev_collab.github_integration_agent import GitHubIntegrationAgent

    result = await GitHubIntegrationAgent.fetch_open_pull_requests()
    if not result["connected"]:
        return {"success": False, "output": result.get("error") or "GitHub not connected"}
    return {"success": True, "output": result["pull_requests"]}


async def handler_get_pr_diff(db, pr_number: int = 0, **kwargs) -> dict:
    """Fetch file-level diff summary for a GitHub pull request."""
    import httpx
    from app.core.config import settings
    from app.agents.dev_collab.github_integration_agent import GitHubIntegrationAgent

    if not GitHubIntegrationAgent.is_configured() or pr_number <= 0:
        return {"success": False, "output": "GitHub not configured or invalid PR number"}
    owner, repo = settings.GITHUB_REPO_OWNER, settings.GITHUB_REPO_NAME
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=GitHubIntegrationAgent._headers()) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            files = [
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                    "patch_preview": (f.get("patch") or "")[:500],
                }
                for f in resp.json()
            ]
        return {"success": True, "output": {"pr_number": pr_number, "files": files}}
    except Exception as exc:
        return {"success": False, "output": str(exc)}


async def handler_sync_github_repo(db, **kwargs) -> dict:
    """Sync live GitHub PRs, rebuild Live Editing Map, and detect conflicts."""
    from app.services.github_sync_service import run_github_sync

    result = await run_github_sync(db, trigger="tool")
    return {"success": bool(result.get("synced")), "output": result}


def register_all_tools() -> None:
    register_tool(Tool(
        name="github_issue_lookup",
        description="Search GitHub's public issue tracker for reports matching an error pattern.",
        keywords=["github", "issue", "public", "report", "search", "lookup", "external", "known issue"],
        handler=handler_github_issue_lookup,
    ))
    register_tool(Tool(
        name="create_escalation_ticket",
        description="Create an enterprise ITSM escalation ticket with an SLA deadline for a human team.",
        keywords=["escalate", "ticket", "sla", "human", "team", "critical", "p1", "unresolved"],
        handler=handler_create_escalation_ticket,
    ))
    register_tool(Tool(
        name="query_knowledge_base",
        description="Look up this system's own long-term memory for a previously-seen pattern.",
        keywords=["memory", "knowledge", "past", "history", "seen before", "learned"],
        handler=handler_query_knowledge_base,
    ))
    register_tool(Tool(
        name="restart_service",
        description="Restart the affected service — fixes transient issues like connection pool exhaustion.",
        keywords=["restart", "connection pool", "timeout", "hang", "unresponsive"],
        handler=handler_restart_service,
    ))
    register_tool(Tool(
        name="clear_cache",
        description="Clear the affected service's cache — fixes stale-data or memory-growth issues.",
        keywords=["cache", "memory leak", "stale", "growing memory"],
        handler=handler_clear_cache,
    ))
    register_tool(Tool(
        name="semantic_conflict_analyze",
        description="Deep semantic/AST analysis of merge conflict risk between two developers.",
        keywords=["semantic", "conflict", "merge", "ast", "logic", "overlap", "analysis"],
        handler=handler_semantic_conflict_analyze,
    ))
    register_tool(Tool(
        name="evaluate_code_quality",
        description="Generate a structured code quality scorecard with A/B/C grade from AST metrics.",
        keywords=["quality", "lint", "complexity", "grade", "scorecard", "review"],
        handler=handler_evaluate_code_quality,
    ))
    register_tool(Tool(
        name="semantic_knowledge_search",
        description="Semantic RAG search over institutional knowledge and past agent decisions.",
        keywords=["search", "rag", "knowledge", "semantic", "similar", "history", "embedding"],
        handler=handler_semantic_knowledge_search,
    ))
    register_tool(Tool(
        name="list_open_prs",
        description="List open pull requests from the configured GitHub repository.",
        keywords=["github", "pull request", "pr", "open", "repo", "branch"],
        handler=handler_list_open_prs,
    ))
    register_tool(Tool(
        name="get_pr_diff",
        description="Fetch file-level diff summary for a GitHub pull request number.",
        keywords=["github", "diff", "patch", "pull request", "pr", "files", "merge"],
        handler=handler_get_pr_diff,
    ))
    register_tool(Tool(
        name="sync_github_repo",
        description="Sync GitHub repo — rebuild Live Editing Map and detect real merge conflicts.",
        keywords=["github", "sync", "scan", "conflict", "live map", "repository"],
        handler=handler_sync_github_repo,
    ))


# Populate the registry as soon as this module is imported.
register_all_tools()
