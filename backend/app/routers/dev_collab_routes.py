"""
Dev-Collaboration Module API routes.
Prefix: /api/dev-collab
"""
import json
import random
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas import StartEditRequest
from app.models.dev_collab import Developer, ConflictEvent, CommitLog
from app.agents.dev_collab.code_watch_agent import CodeWatchAgent, DEMO_DEV_NAMES
from app.agents.dev_collab.conflict_prediction_agent import OverlapDetectionAgent, ConflictPredictionAgent
from app.agents.dev_collab.resolution_suggestion_agent import ResolutionSuggestionAgent
from app.agents.dev_collab.resolution_synthesizer_agent import ResolutionSynthesizerAgent
from app.agents.dev_collab.repository_discovery_agent import RepositoryDiscoveryAgent
from app.agents.dev_collab.github_integration_agent import GitHubIntegrationAgent
from app.agents.coordinator_agent import CoordinatorAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.notification_agent import NotificationAgent
from app.services.synthetic_data_generator import random_edit_event
from app.services.github_sync_service import enrich_and_notify_conflict, run_github_sync
from app.services.github_webhook_service import GitHubWebhookService
from app.services import hitl_service, repo_service
from app.core.config import settings, simulate_endpoints_enabled
from app.core.datetime_utils import utc_iso
from app.services.demo_filters import is_demo_commit
from app.routers.websocket_routes import manager

router = APIRouter(prefix="/api/dev-collab", tags=["Dev Collaboration"])


class RejectIn(BaseModel):
    note: str = ""


class DeferIn(BaseModel):
    note: str = ""


class RepoSubmitIn(BaseModel):
    repo_url: str

# Demo-safe developer pool used by the "Simulate Conflict" button (pytest / dev API only).
DEMO_DEV_COLORS = {
    "Priya Sharma": "#4F8CFF",
    "Arjun Mehta": "#FF6B6B",
    "Sneha Reddy": "#3ECF8E",
    "Karthik Rao": "#F5A623",
}
DEMO_DEV_NAME_PAIRS = [(name, DEMO_DEV_COLORS[name]) for name in DEMO_DEV_NAMES]


async def _enrich_and_notify_conflict(
    db: AsyncSession,
    event: ConflictEvent,
    dev_a_name: str,
    dev_b_name: str,
    risk_score: float,
) -> dict:
    return await enrich_and_notify_conflict(db, event, dev_a_name, dev_b_name, risk_score)


@router.post("/edit-session/start")
async def start_edit_session(
    payload: StartEditRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Register that a developer started editing a file/function (live presence)."""
    dev = await CodeWatchAgent.get_or_create_developer(db, payload.developer_name)
    session = await CodeWatchAgent.start_edit_session(
        db, developer_id=dev.id, file_path=payload.file_path, function_name=payload.function_name
    )
    await manager.broadcast("edit_session_started", {
        "session_id": session.id, "developer_id": dev.id, "developer_name": dev.name,
        "file_path": payload.file_path, "function_name": payload.function_name,
    })
    return {"session_id": session.id, "developer_id": dev.id}


@router.post("/edit-session/{session_id}/end")
async def end_edit_session_route(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark an edit session as finished (developer saved/pushed their work)."""
    await CodeWatchAgent.end_edit_session(db, session_id)
    await manager.broadcast("edit_session_ended", {"session_id": session_id})
    return {"ended": session_id}


@router.get("/active-sessions")
async def get_active_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Live map from GitHub repo scan (demo hardcoded names excluded)."""
    sessions = await CodeWatchAgent.get_active_sessions(db, github_only=True)
    output = []
    for s in sessions:
        dev = await db.get(Developer, s.developer_id)
        output.append({
            "session_id": s.id,
            "developer_id": s.developer_id,
            "developer_name": dev.name if dev else f"Dev #{s.developer_id}",
            "avatar_color": dev.avatar_color if dev else "#6C63FF",
            "file_path": s.file_path,
            "function_name": s.function_name,
            "started_at": utc_iso(s.started_at),
            "source": "github",
        })
    return output


@router.post("/check-conflicts")
async def check_conflicts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Runs Overlap Detection + Conflict Prediction across all active sessions.
    Risk score factors in how long the two developers have actually been
    overlapping (real elapsed time, not a fixed guess).
    """
    overlaps = await OverlapDetectionAgent.find_overlaps(db)
    created_events = []

    for overlap in overlaps:
        minutes_overlap = 5.0
        started = overlap.get("overlap_started_at")
        if started:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            minutes_overlap = max((datetime.now(timezone.utc) - started).total_seconds() / 60, 1)

        risk_score = ConflictPredictionAgent.calculate_risk_score(same_function=True, minutes_overlap=minutes_overlap)
        event = await ConflictPredictionAgent.create_conflict_event(
            db,
            file_path=overlap["file_path"],
            function_name=overlap["function_name"],
            dev_a_id=overlap["dev_a_id"],
            dev_b_id=overlap["dev_b_id"],
            risk_score=risk_score,
        )
        created_events.append(event)

        dev_a = await db.get(Developer, overlap["dev_a_id"])
        dev_b = await db.get(Developer, overlap["dev_b_id"])
        dev_a_name = dev_a.name if dev_a else "Dev A"
        dev_b_name = dev_b.name if dev_b else "Dev B"
        await CoordinatorAgent.log_decision(
            db=db,
            agent_name="Conflict Prediction Agent",
            module="dev_collab",
            decision_summary=(
                f"Predicted conflict risk {risk_score}% in {event.file_path} "
                f"({event.function_name}) between {dev_a_name} and {dev_b_name}"
            ),
            used_llm=False,
            related_entity_id=event.id,
        )

        await _enrich_and_notify_conflict(db, event, dev_a_name, dev_b_name, risk_score)

        await manager.broadcast("conflict_detected", {
            "conflict_id": event.id,
            "file_path": event.file_path,
            "function_name": event.function_name,
            "dev_a": dev_a_name,
            "dev_b": dev_b_name,
            "risk_score": risk_score,
        })

    return {"conflicts_found": len(created_events), "events": [e.id for e in created_events]}


@router.get("/conflicts")
async def list_conflicts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Predicted/resolved conflicts from real GitHub sync only (seed/simulated hidden)."""
    result = await db.execute(
        select(ConflictEvent)
        .where(ConflictEvent.source == "github")
        .order_by(ConflictEvent.created_at.desc())
    )
    conflicts = result.scalars().all()

    output = []
    for c in conflicts:
        dev_a = await db.get(Developer, c.dev_a_id)
        dev_b = await db.get(Developer, c.dev_b_id)
        output.append({
            "id": c.id,
            "file_path": c.file_path,
            "function_name": c.function_name,
            "dev_a": dev_a.name if dev_a else f"Dev #{c.dev_a_id}",
            "dev_b": dev_b.name if dev_b else f"Dev #{c.dev_b_id}",
            "risk_score": c.risk_score,
            "status": c.status,
            "source": c.source,
            "source_url": c.source_url,
            "ai_suggestion": c.ai_suggestion,
            "code_review_notes": c.code_review_notes,
            "discovery_context": _parse_json_field(c.discovery_context),
            "semantic_analysis": _parse_json_field(c.semantic_analysis),
            "quality_report": _parse_json_field(c.quality_report),
            "resolution_options": _parse_json_field(c.resolution_options),
            "approval_status": c.approval_status,
            "resolved_by_name": c.resolved_by_name,
            "user_note": c.user_note,
            "created_at": c.created_at,
        })
    return output


def _parse_json_field(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


@router.post("/conflicts/{conflict_id}/suggest-resolution")
async def suggest_resolution(
    conflict_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI suggests resolution — sets pending_approval; user must approve (HITL)."""
    conflict = await db.get(ConflictEvent, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")

    dev_a = await db.get(Developer, conflict.dev_a_id)
    dev_b = await db.get(Developer, conflict.dev_b_id)
    dev_a_name = dev_a.name if dev_a else "Developer A"
    dev_b_name = dev_b.name if dev_b else "Developer B"

    semantic = _parse_json_field(conflict.semantic_analysis) or {}
    quality = _parse_json_field(conflict.quality_report) or {}

    synth = await ResolutionSynthesizerAgent.synthesize(
        db,
        dev_a_name,
        dev_b_name,
        conflict.file_path,
        conflict.function_name,
        semantic_analysis=semantic if isinstance(semantic, dict) else None,
        quality_report=quality if isinstance(quality, dict) else None,
    )
    conflict.resolution_options = json.dumps(synth["options"])

    result = await ResolutionSuggestionAgent.suggest(
        db, dev_a_name, dev_b_name, conflict.file_path, conflict.function_name
    )

    conflict.ai_suggestion = synth["suggestion"] or result["suggestion"]
    conflict.status = "predicted"
    conflict.approval_status = "pending_approval"
    conflict.updated_by_user_id = user.id
    db.add(conflict)
    await db.commit()

    await MemoryAgent.remember(
        db,
        category="conflict_resolution",
        key_signature=f"{conflict.file_path}:{conflict.function_name}",
        insight=conflict.ai_suggestion or "Suggested merge resolution",
    )

    await manager.broadcast("conflict_suggestion_ready", {
        "conflict_id": conflict.id,
        "suggestion": conflict.ai_suggestion,
        "approval_status": "pending_approval",
    })

    return {
        "conflict_id": conflict.id,
        "suggestion": conflict.ai_suggestion,
        "approval_status": "pending_approval",
        **result,
        "synthesizer": synth,
    }


@router.post("/conflicts/{conflict_id}/approve")
async def approve_conflict_route(
    conflict_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await hitl_service.approve_conflict(db, conflict_id, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/conflicts/{conflict_id}/reject")
async def reject_conflict_route(
    conflict_id: int,
    payload: RejectIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await hitl_service.reject_conflict(db, conflict_id, user, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/conflicts/{conflict_id}/resolve-later")
async def defer_conflict_route(
    conflict_id: int,
    payload: DeferIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await hitl_service.defer_conflict(db, conflict_id, user, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/conflicts/{conflict_id}/undo")
async def undo_conflict_route(
    conflict_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await hitl_service.undo_last_action(db, conflict_id, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/repo/submit")
async def submit_repo_route(
    payload: RepoSubmitIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await repo_service.submit_user_repo(db, user, payload.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/repo/mine")
async def get_my_repo_route(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await repo_service.get_user_repo(db, user)


@router.post("/repo/recheck")
async def recheck_repo_route(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await repo_service.recheck_user_repo(db, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/repository/discovery")
async def repository_discovery(
    file_path: str | None = None,
    function_name: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Phase 1 — AST repository discovery and symbol indexing."""
    result = await RepositoryDiscoveryAgent.discover(db, file_path, function_name)
    return result


@router.get("/commits")
async def list_commits(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recent commit history — demo seed commits hidden; real GitHub resolutions shown."""
    result = await db.execute(select(CommitLog).order_by(CommitLog.created_at.desc()).limit(50))
    commits = result.scalars().all()
    output = []
    for c in commits:
        if await is_demo_commit(db, c):
            continue
        dev = await db.get(Developer, c.developer_id)
        output.append({
            "id": c.id,
            "commit_hash": c.commit_hash,
            "developer_name": dev.name if dev else f"Dev #{c.developer_id}",
            "file_path": c.file_path,
            "message": c.message,
            "had_conflict": c.had_conflict,
            "created_at": c.created_at,
        })
        if len(output) >= 20:
            break
    return output


@router.post("/simulate-demo-conflict")
async def simulate_demo_conflict(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Demo-safe one-click scenario generator: creates two developers editing the
    SAME file/function at the same time, runs overlap + conflict-risk
    detection, and returns the result. No real IDE/git integration needed —
    perfect for a live presentation where you can't rely on external tools.
    """
    if not simulate_endpoints_enabled():
        raise HTTPException(status_code=403, detail="Simulate endpoints are disabled in production.")
    (dev_a_name, dev_a_color), (dev_b_name, dev_b_color) = random.sample(DEMO_DEV_NAME_PAIRS, 2)
    edit_event = random_edit_event()

    dev_a = await CodeWatchAgent.get_or_create_developer(db, dev_a_name, avatar_color=dev_a_color)
    dev_b = await CodeWatchAgent.get_or_create_developer(db, dev_b_name, avatar_color=dev_b_color)

    await CodeWatchAgent.start_edit_session(db, dev_a.id, edit_event["file_path"], edit_event["function_name"])
    await CodeWatchAgent.start_edit_session(db, dev_b.id, edit_event["file_path"], edit_event["function_name"])

    risk_score = ConflictPredictionAgent.calculate_risk_score(same_function=True, minutes_overlap=6)
    conflict = await ConflictPredictionAgent.create_conflict_event(
        db, edit_event["file_path"], edit_event["function_name"], dev_a.id, dev_b.id, risk_score
    )

    await CoordinatorAgent.log_decision(
        db=db,
        agent_name="Conflict Prediction Agent",
        module="dev_collab",
        decision_summary=(
            f"Demo conflict predicted: risk {risk_score}% in {edit_event['file_path']} "
            f"({edit_event['function_name']}) between {dev_a_name} and {dev_b_name}"
        ),
        used_llm=False,
        related_entity_id=conflict.id,
    )

    await _enrich_and_notify_conflict(db, conflict, dev_a_name, dev_b_name, risk_score)

    payload = {
        "conflict_id": conflict.id,
        "dev_a": dev_a_name,
        "dev_b": dev_b_name,
        "file_path": edit_event["file_path"],
        "function_name": edit_event["function_name"],
        "risk_score": risk_score,
    }
    await manager.broadcast("conflict_detected", payload)
    return payload


@router.get("/github/status")
async def github_status():
    """Whether real GitHub integration is configured, webhook URL, and which repo it points to."""
    return {
        "configured": GitHubIntegrationAgent.is_configured(),
        "repo": f"{settings.GITHUB_REPO_OWNER}/{settings.GITHUB_REPO_NAME}" if GitHubIntegrationAgent.is_configured() else None,
        "webhook_url": GitHubWebhookService.webhook_url(),
        "webhook_secret_configured": bool((settings.GITHUB_WEBHOOK_SECRET or "").strip()),
        "webhook_events": ["pull_request"],
    }


@router.post("/github/sync")
async def github_sync(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Phase A — Real GitHub Integration (manual trigger).
    Fetches LIVE open Pull Requests from a real repository.
    """
    return await run_github_sync(db, trigger="manual")


@router.post("/github/webhook")
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    """
    GitHub webhook endpoint — PR opened/updated triggers instant conflict sync.
    Configure in GitHub repo: Settings → Webhooks → Payload URL = webhook_url from /github/status
    """
    body = await request.body()
    signature = x_hub_signature_256 or GitHubWebhookService.signature_header_from_request(request)
    if not GitHubWebhookService.verify_signature(body, signature):
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid GitHub webhook signature. "
                "Set the GitHub webhook Secret to exactly match GITHUB_WEBHOOK_SECRET in backend/.env, "
                "then click Redeliver on the failed delivery."
            ),
        )

    try:
        payload = GitHubWebhookService.parse_payload(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    result = await GitHubWebhookService.handle_event(db, x_github_event, payload)
    return result


@router.get("/github/webhook")
async def github_webhook_info():
    """Helpful for browser checks — webhooks must use POST from GitHub."""
    return {
        "message": "GitHub webhook endpoint is active. GitHub must POST here (browser GET is not supported).",
        "webhook_url": GitHubWebhookService.webhook_url(),
        "secret_configured": bool((settings.GITHUB_WEBHOOK_SECRET or "").strip()),
    }
