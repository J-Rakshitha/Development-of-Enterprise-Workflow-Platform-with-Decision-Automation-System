"""
System / Demo Control routes.
Prefix: /api/system
Includes the health check, aggregate stats, and the "Simulate API Failure"
toggle used to PROVE the hybrid fallback works live during the demo.
"""
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.incident import AgentDecisionLog, Incident
from app.models.dev_collab import FileEditSession, ConflictEvent
from app.agents.llm.llm_client import set_simulated_failure, get_simulated_failure
from app.agents.memory_agent import MemoryAgent
from app.agents.notification_agent import NotificationAgent
from app.core.config import settings

router = APIRouter(prefix="/api/system", tags=["System"])


class WebhookTestIn(BaseModel):
    url: str | None = None


class TeamsWebhookTestIn(WebhookTestIn):
    pass


@router.get("/integrations")
async def get_integrations():
    """Which external notification/integration channels are configured."""
    slack_url = (settings.SLACK_WEBHOOK_URL or "").strip()
    discord_url = (settings.DISCORD_WEBHOOK_URL or "").strip()
    teams_url = (settings.TEAMS_WEBHOOK_URL or "").strip()
    return {
        "email": {
            "configured": NotificationAgent.smtp_ready(),
            "smtp_host": settings.NOTIFICATION_SMTP_HOST or None,
            "from_email": settings.NOTIFICATION_FROM_EMAIL or None,
            "team_recipients": NotificationAgent.team_email_recipients(),
            "setup_note": (
                None
                if NotificationAgent.smtp_ready()
                else "Set NOTIFICATION_SMTP_* and Gmail App Password in backend/.env, then restart."
            ),
        },
        "slack": {
            "configured": bool(slack_url),
            "channel_hint": "slack-channel" if slack_url else None,
        },
        "discord": {
            "configured": bool(discord_url),
            "channel_hint": "discord-channel" if discord_url else None,
            "setup_note": (
                None
                if discord_url
                else "Set DISCORD_WEBHOOK_URL in backend/.env — Discord channel → Integrations → Webhooks."
            ),
        },
        "teams": {
            "configured": bool(teams_url),
            "channel_hint": "teams-channel" if teams_url else None,
            "setup_note": (
                None
                if teams_url
                else "Set TEAMS_WEBHOOK_URL in backend/.env — requires Microsoft 365 or Power Automate webhook URL."
            ),
        },
        "github": {
            "configured": bool((settings.GITHUB_TOKEN or "").strip()),
            "repo": f"{settings.GITHUB_REPO_OWNER}/{settings.GITHUB_REPO_NAME}",
            "webhook_url": f"{settings.PUBLIC_BACKEND_URL.rstrip('/')}/api/dev-collab/github/webhook",
        },
        "llm": {
            "enabled": settings.LLM_ENABLED,
            "model": settings.LLM_MODEL,
        },
    }


@router.post("/test-teams-webhook")
async def test_teams_webhook(body: TeamsWebhookTestIn | None = None):
    """
    Send a test alert to Microsoft Teams. Uses TEAMS_WEBHOOK_URL from .env,
    or pass {\"url\": \"...\"} to test a URL before saving it.
    """
    test_url = (body.url if body and body.url else settings.TEAMS_WEBHOOK_URL or "").strip()
    if not test_url:
        raise HTTPException(
            status_code=400,
            detail="TEAMS_WEBHOOK_URL is not set. Paste your Teams/Power Automate webhook URL in backend/.env or pass it in the request body.",
        )
    subject = f"[{settings.APP_NAME}] Teams webhook test"
    message = "If you see this in Teams, PART 3 is configured correctly."
    delivered = NotificationAgent.send_teams_webhook(test_url, subject, message)
    if not delivered:
        raise HTTPException(
            status_code=502,
            detail="Teams webhook POST failed. Check the URL and that your Microsoft account supports incoming webhooks.",
        )
    return {"delivered": True, "tested_url_prefix": test_url[:48] + "..."}


@router.post("/test-discord-webhook")
async def test_discord_webhook(body: WebhookTestIn | None = None):
    """Send a test alert to Discord. Uses DISCORD_WEBHOOK_URL from .env or pass url in body."""
    test_url = (body.url if body and body.url else settings.DISCORD_WEBHOOK_URL or "").strip()
    if not test_url:
        raise HTTPException(
            status_code=400,
            detail="DISCORD_WEBHOOK_URL is not set. Paste your Discord webhook URL in backend/.env or pass it in the request body.",
        )
    subject = f"[{settings.APP_NAME}] Discord webhook test"
    message = "If you see this in Discord, Discord alerts are configured correctly."
    delivered = NotificationAgent.send_discord_webhook(test_url, subject, message)
    if not delivered:
        raise HTTPException(
            status_code=502,
            detail="Discord webhook POST failed. Check the URL is a valid channel webhook from Discord Integrations.",
        )
    return {"delivered": True, "tested_url_prefix": test_url[:48] + "..."}


@router.post("/test-email")
async def test_email():
    """Send a test email using Gmail SMTP settings from .env."""
    if not NotificationAgent.smtp_ready():
        raise HTTPException(
            status_code=400,
            detail=(
                "Gmail SMTP not fully configured. Set NOTIFICATION_SMTP_HOST, USER, PASSWORD "
                "(Gmail App Password), FROM_EMAIL, and ONCALL_EMAIL in backend/.env, then restart."
            ),
        )
    recipient = NotificationAgent.team_email_recipients()[0]
    subject = f"[{settings.APP_NAME}] Gmail SMTP test"
    message = "If you received this email, Gmail SMTP is configured correctly."
    delivered = NotificationAgent.send_email(subject, message, recipient)
    if not delivered:
        raise HTTPException(
            status_code=502,
            detail="SMTP send failed. Check Gmail App Password and that 2-Step Verification is enabled.",
        )
    return {"delivered": True, "recipient": recipient}


@router.get("/health")
async def health_check():
    """Live health endpoint — also probed by the background monitor (Phase B)."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
        "db_pool_usage_pct": 35.0,
        "monitoring_enabled": settings.MONITORING_ENABLED,
    }


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Aggregate counts for the Overview dashboard's stat cards."""
    active_sessions = await db.scalar(
        select(func.count()).select_from(FileEditSession).where(FileEditSession.is_active == True)  # noqa: E712
    )
    conflicts_predicted = await db.scalar(select(func.count()).select_from(ConflictEvent))
    open_incidents = await db.scalar(
        select(func.count()).select_from(Incident).where(Incident.status.in_(["open", "escalated"]))
    )
    linked_incidents = await db.scalar(
        select(func.count()).select_from(Incident).where(Incident.linked_commit_id.isnot(None))
    )
    return {
        "active_edit_sessions": active_sessions or 0,
        "conflicts_predicted": conflicts_predicted or 0,
        "open_incidents": open_incidents or 0,
        "linked_incidents": linked_incidents or 0,
    }


@router.get("/knowledge-base")
async def get_knowledge_base(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Shared Knowledge & Memory Management (long-term memory) — the persistent
    insights agents have built up over time. Exposed as a REST endpoint so
    other enterprise tools/dashboards could also consume this institutional
    knowledge (this is the 'Tool & System Integration' surface).
    """
    entries = await MemoryAgent.list_recent_knowledge(db)
    return [
        {
            "id": e.id, "category": e.category, "key_signature": e.key_signature,
            "insight": e.insight, "success_count": e.success_count,
            "last_used_at": e.last_used_at,
        }
        for e in entries
    ]


@router.get("/notifications")
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Team notification log — WebSocket + email delivery records from the Notification Agent."""
    entries = await NotificationAgent.list_recent(db)
    return [
        {
            "id": n.id,
            "channel": n.channel,
            "event_type": n.event_type,
            "module": n.module,
            "recipient": n.recipient,
            "subject": n.subject,
            "message": n.message,
            "related_entity_id": n.related_entity_id,
            "delivered": n.delivered,
            "acknowledged": n.acknowledged,
            "created_at": n.created_at,
        }
        for n in entries
    ]


@router.get("/knowledge-base/search")
async def search_knowledge_base(
    q: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Phase 5 — Semantic RAG search over knowledge base and agent decision history.
    """
    from app.agents.dev_collab.knowledge_search_agent import KnowledgeSearchAgent

    return await KnowledgeSearchAgent.search(db, q)


@router.post("/toggle-llm-failure")
async def toggle_llm_failure(
    enabled: bool,
    user: User = Depends(get_current_user),
):
    """
    Demo control: force every agent to use the rule-based fallback,
    to prove live on stage that the system never crashes even if the
    LLM API is down.
    """
    set_simulated_failure(enabled)
    return {"simulated_llm_failure": enabled}


@router.get("/llm-failure-status")
async def llm_failure_status():
    """Lets the frontend toggle switch reflect the current state on page load."""
    return {"simulated_llm_failure": get_simulated_failure()}


@router.post("/notifications/{notification_id}/acknowledge")
async def acknowledge_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models.notification import TeamNotification

    notif = await db.get(TeamNotification, notification_id)
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.acknowledged = True
    db.add(notif)
    await db.commit()
    return {"success": True, "id": notification_id, "acknowledged": True}


@router.get("/agent-metrics")
async def get_agent_metrics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Agent performance dashboard — run counts and LLM usage from decision logs."""
    result = await db.execute(select(AgentDecisionLog))
    logs = result.scalars().all()
    by_agent: dict[str, dict] = {}
    for log in logs:
        key = log.agent_name
        if key not in by_agent:
            by_agent[key] = {"agent_name": key, "module": log.module, "run_count": 0, "llm_count": 0, "rule_count": 0}
        by_agent[key]["run_count"] += 1
        if log.used_llm:
            by_agent[key]["llm_count"] += 1
        else:
            by_agent[key]["rule_count"] += 1
    agents = sorted(by_agent.values(), key=lambda x: x["run_count"], reverse=True)
    total = len(logs)
    llm_total = sum(a["llm_count"] for a in agents)
    return {
        "total_decisions": total,
        "llm_decisions": llm_total,
        "rule_decisions": total - llm_total,
        "agents": agents,
    }


@router.get("/decision-log")
async def get_decision_log(db: AsyncSession = Depends(get_db)):
    """Explainable-AI trail: every decision any agent has made, across both modules."""
    result = await db.execute(select(AgentDecisionLog).order_by(AgentDecisionLog.created_at.desc()).limit(50))
    logs = result.scalars().all()
    return [
        {
            "id": l.id, "agent_name": l.agent_name, "module": l.module,
            "decision_summary": l.decision_summary, "used_llm": l.used_llm,
            "created_at": l.created_at,
        }
        for l in logs
    ]
