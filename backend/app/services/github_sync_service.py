"""
Shared GitHub sync logic — used by manual sync and webhook-triggered sync.
"""
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.dev_collab import ConflictEvent
from app.agents.dev_collab.github_integration_agent import GitHubIntegrationAgent
from app.agents.dev_collab.conflict_prediction_agent import ConflictPredictionAgent
from app.agents.dev_collab.code_watch_agent import CodeWatchAgent
from app.agents.coordinator_agent import CoordinatorAgent
from app.routers.websocket_routes import manager


async def enrich_and_notify_conflict(
    db: AsyncSession,
    event,
    dev_a_name: str,
    dev_b_name: str,
    risk_score: float,
    recipients: list[str] | None = None,
) -> dict:
    """
    Enterprise pipeline:
    Discovery → Semantic Analysis → Quality → Code Review → Notify
    """
    from app.agents.dev_collab.repository_discovery_agent import RepositoryDiscoveryAgent
    from app.agents.dev_collab.semantic_analysis_agent import SemanticAnalysisAgent
    from app.agents.dev_collab.quality_agent import QualityAgent
    from app.agents.dev_collab.code_review_agent import CodeReviewAgent
    from app.agents.notification_agent import NotificationAgent

    discovery = await RepositoryDiscoveryAgent.discover(
        db, file_path=event.file_path, function_name=event.function_name
    )
    event.discovery_context = json.dumps(discovery["context"])

    semantic = await SemanticAnalysisAgent.analyze(
        db,
        event.file_path,
        event.function_name,
        dev_a_name,
        dev_b_name,
        risk_score,
        discovery_context=discovery["context"],
    )
    event.semantic_analysis = json.dumps(semantic)

    quality = await QualityAgent.evaluate(
        db,
        event.file_path,
        event.function_name,
        risk_score,
        semantic_risk=semantic.get("semantic_risk_score"),
        discovery_context=discovery["context"],
    )
    event.quality_report = json.dumps(quality)

    review = await CodeReviewAgent.review(
        db, event.file_path, event.function_name or "", dev_a_name, dev_b_name, risk_score
    )
    event.code_review_notes = review["review"]
    db.add(event)
    await db.commit()
    await db.refresh(event)

    await NotificationAgent.notify_conflict_detected(
        db,
        conflict_id=event.id,
        file_path=event.file_path,
        function_name=event.function_name,
        dev_a=dev_a_name,
        dev_b=dev_b_name,
        risk_score=risk_score,
        code_review=review["review"],
        recipients=recipients,
    )
    return {
        "discovery": discovery,
        "semantic": semantic,
        "quality": quality,
        "review": review,
    }


async def run_github_sync(db: AsyncSession, trigger: str = "manual") -> dict:
    """
    Fetch live PRs from GitHub and create conflict events for confirmed/predicted conflicts.
    trigger: 'manual' | 'webhook' — for audit/logging only.
    """
    result = await GitHubIntegrationAgent.fetch_open_pull_requests()
    if not result["connected"]:
        return {"synced": False, "error": result["error"], "conflicts_found": 0, "trigger": trigger}

    found_conflicts = GitHubIntegrationAgent.find_real_conflicts(result["pull_requests"])
    created = []
    skipped_duplicates = 0

    sessions_created = await CodeWatchAgent.sync_live_map_from_github(db, result["pull_requests"])
    await manager.broadcast("repo_scanned", {
        "source": "github",
        "sessions_created": sessions_created,
        "pull_requests": len(result["pull_requests"]),
    })

    for fc in found_conflicts:
        existing_stmt = select(ConflictEvent).where(
            ConflictEvent.source == "github",
            ConflictEvent.file_path == fc["file_path"],
            ConflictEvent.function_name == fc["function_name"],
            ConflictEvent.status == "predicted",
        )
        existing = (await db.execute(existing_stmt)).scalars().first()
        if existing:
            skipped_duplicates += 1
            continue

        dev_a = await CodeWatchAgent.get_or_create_developer(db, fc["dev_a"], avatar_color="#4F8CFF")
        dev_b = await CodeWatchAgent.get_or_create_developer(db, fc["dev_b"], avatar_color="#FF6B6B")

        event = await ConflictPredictionAgent.create_conflict_event(
            db,
            file_path=fc["file_path"],
            function_name=fc["function_name"],
            dev_a_id=dev_a.id,
            dev_b_id=dev_b.id,
            risk_score=fc["risk_score"],
            source="github",
            source_url=fc["source_url"],
        )
        created.append(event.id)

        await CoordinatorAgent.log_decision(
            db=db,
            agent_name="GitHub Integration Agent",
            module="dev_collab",
            decision_summary=(
                f"{'Confirmed' if fc['type'] == 'confirmed' else 'Predicted'} conflict in {fc['file_path']} "
                f"between {fc['dev_a']} and {fc['dev_b']} (trigger: {trigger})."
            ),
            used_llm=False,
            related_entity_id=event.id,
        )

        await enrich_and_notify_conflict(
            db, event, fc["dev_a"], fc["dev_b"], fc["risk_score"],
            recipients=_github_notification_recipients(fc["dev_a"], fc["dev_b"]),
        )

        await manager.broadcast("conflict_detected", {
            "conflict_id": event.id,
            "file_path": fc["file_path"],
            "function_name": fc["function_name"],
            "dev_a": fc["dev_a"],
            "dev_b": fc["dev_b"],
            "risk_score": fc["risk_score"],
            "source": "github",
            "trigger": trigger,
        })

    return {
        "synced": True,
        "pull_requests_checked": len(result["pull_requests"]),
        "conflicts_found": len(created),
        "conflicts_already_known": skipped_duplicates,
        "conflict_ids": created,
        "live_map_sessions": sessions_created,
        "trigger": trigger,
    }


def _github_notification_recipients(dev_a: str, dev_b: str) -> list[str]:
    recipients = []
    for name in (dev_a, dev_b):
        if name and name != "base branch" and name not in recipients:
            recipients.append(f"github:{name}")
    return recipients
