"""Milestone 4 — Complex workflow orchestration engine."""
import json
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.coordinator_agent import CoordinatorAgent
from app.core.config import settings
from app.core.datetime_utils import utc_iso
from app.agents.dev_collab.resolution_suggestion_agent import ResolutionSuggestionAgent
from app.agents.dev_collab.resolution_synthesizer_agent import ResolutionSynthesizerAgent
from app.agents.dev_collab.semantic_analysis_agent import SemanticAnalysisAgent
from app.agents.memory_agent import MemoryAgent
from app.models.dev_collab import CommitLog, ConflictEvent, Developer
from app.models.incident import Incident
from app.models.user import User
from app.models.workflow_engine import WorkflowDefinition, WorkflowJob, WorkflowRun, WorkflowStepLog
from app.routers.websocket_routes import manager
from app.services import hitl_service
from app.services import job_queue_service
from app.services.incident_pipeline import run_incident_pipeline
from app.services.workflow_definitions import WORKFLOW_TEMPLATES, template_steps, template_to_json

logger = logging.getLogger("workflow_orchestrator")

MAX_STEP_RETRIES = 3


async def seed_workflow_definitions(db: AsyncSession) -> None:
    for key, tpl in WORKFLOW_TEMPLATES.items():
        existing = await db.scalar(
            select(WorkflowDefinition).where(WorkflowDefinition.template_key == key)
        )
        if existing:
            existing.name = tpl["name"]
            existing.description = tpl["description"]
            existing.steps_json = template_to_json(key)
            existing.is_active = True
        else:
            db.add(WorkflowDefinition(
                template_key=key,
                name=tpl["name"],
                description=tpl["description"],
                steps_json=template_to_json(key),
            ))
    await db.commit()


def _parse_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _serialize_run(run: WorkflowRun, definition: WorkflowDefinition | None = None) -> dict:
    ctx = _parse_json(run.context_json)
    return {
        "id": run.id,
        "template_key": run.template_key,
        "name": definition.name if definition else run.template_key,
        "status": run.status,
        "current_step_index": run.current_step_index,
        "conflict_id": run.conflict_id,
        "incident_id": run.incident_id,
        "context": ctx,
        "error_message": run.error_message,
        "started_at": utc_iso(run.started_at),
        "completed_at": utc_iso(run.completed_at),
        "updated_at": utc_iso(run.updated_at),
    }


async def list_definitions(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.is_active == True).order_by(WorkflowDefinition.id)  # noqa: E712
    )
    defs = result.scalars().all()
    out = []
    for d in defs:
        steps = json.loads(d.steps_json)
        out.append({
            "template_key": d.template_key,
            "name": d.name,
            "description": d.description,
            "step_count": len(steps) if isinstance(steps, list) else 0,
            "steps": steps,
        })
    return out


async def _log_step(
    db: AsyncSession,
    run: WorkflowRun,
    step: dict,
    step_index: int,
    status: str,
    output: dict | None = None,
    error: str | None = None,
) -> WorkflowStepLog:
    now = datetime.utcnow()
    entry = WorkflowStepLog(
        run_id=run.id,
        step_index=step_index,
        step_id=step["id"],
        agent_name=step["agent"],
        module=step["module"],
        status=status,
        output_json=json.dumps(output) if output else None,
        error_message=error,
        started_at=now if status == "running" else None,
        completed_at=now if status in ("completed", "failed", "waiting_hitl") else None,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def _broadcast_step(run: WorkflowRun, step: dict, status: str, detail: dict | None = None) -> None:
    await manager.broadcast("workflow_step_updated", {
        "run_id": run.id,
        "template_key": run.template_key,
        "step_id": step["id"],
        "agent_name": step["agent"],
        "status": status,
        "run_status": run.status,
        **(detail or {}),
    })


async def _execute_step(
    db: AsyncSession,
    run: WorkflowRun,
    user: User,
    step: dict,
    step_index: int,
) -> str:
    """Execute one workflow step. Returns next action: continue | pause_hitl | done | failed."""
    step_id = step["id"]
    ctx = _parse_json(run.context_json)

    await _log_step(db, run, step, step_index, "running")
    await _broadcast_step(run, step, "running")

    try:
        if step_id == "validate_conflict":
            conflict_id = ctx.get("conflict_id") or run.conflict_id
            if not conflict_id:
                raise ValueError("conflict_id required for this workflow")
            conflict = await db.get(ConflictEvent, conflict_id)
            if not conflict:
                raise ValueError(f"Conflict {conflict_id} not found")
            run.conflict_id = conflict_id
            ctx["conflict_id"] = conflict_id
            run.context_json = json.dumps(ctx)
            await CoordinatorAgent.log_decision(
                db, "Workflow Orchestrator", "dev_collab",
                f"Validated conflict #{conflict_id} for workflow run #{run.id}.",
                False, conflict_id,
            )

        elif step_id == "semantic_review":
            conflict = await db.get(ConflictEvent, run.conflict_id)
            if conflict and not conflict.semantic_analysis:
                dev_a = await db.get(Developer, conflict.dev_a_id)
                dev_b = await db.get(Developer, conflict.dev_b_id)
                result = await SemanticAnalysisAgent.analyze(
                    db,
                    conflict.file_path,
                    conflict.function_name,
                    dev_a.name if dev_a else "Dev A",
                    dev_b.name if dev_b else "Dev B",
                    float(conflict.risk_score or 50),
                )
                conflict.semantic_analysis = json.dumps(result)
                db.add(conflict)
                await db.commit()

        elif step_id == "ai_suggestion":
            conflict = await db.get(ConflictEvent, run.conflict_id)
            if not conflict:
                raise ValueError("Conflict not found for AI suggestion step")
            dev_a = await db.get(Developer, conflict.dev_a_id)
            dev_b = await db.get(Developer, conflict.dev_b_id)
            dev_a_name = dev_a.name if dev_a else "Developer A"
            dev_b_name = dev_b.name if dev_b else "Developer B"

            semantic = _parse_json(conflict.semantic_analysis) if conflict.semantic_analysis else {}
            quality = _parse_json(conflict.quality_report) if conflict.quality_report else {}

            synth = await ResolutionSynthesizerAgent.synthesize(
                db, dev_a_name, dev_b_name, conflict.file_path, conflict.function_name,
                semantic_analysis=semantic if isinstance(semantic, dict) else None,
                quality_report=quality if isinstance(quality, dict) else None,
            )
            conflict.resolution_options = json.dumps(synth["options"])
            result = await ResolutionSuggestionAgent.suggest(
                db, dev_a_name, dev_b_name, conflict.file_path, conflict.function_name,
            )
            conflict.ai_suggestion = synth["suggestion"] or result["suggestion"]
            conflict.status = "predicted"
            conflict.approval_status = "pending_approval"
            conflict.updated_by_user_id = user.id
            db.add(conflict)
            await db.commit()
            await MemoryAgent.remember(
                db, "conflict_resolution",
                f"{conflict.file_path}:{conflict.function_name}",
                conflict.ai_suggestion or "Workflow AI suggestion",
            )
            ctx["suggestion"] = conflict.ai_suggestion
            run.context_json = json.dumps(ctx)

        elif step_id == "hitl_gate":
            conflict = await db.get(ConflictEvent, run.conflict_id)
            if not conflict:
                raise ValueError("Conflict not found at HITL gate")
            if conflict.approval_status == "approved" and conflict.status == "resolved":
                pass
            elif conflict.approval_status != "pending_approval":
                conflict.approval_status = "pending_approval"
                db.add(conflict)
                await db.commit()
            run.status = "waiting_hitl"
            run.updated_at = datetime.utcnow()
            db.add(run)
            await _log_step(db, run, step, step_index, "waiting_hitl", {"conflict_id": run.conflict_id})
            await _broadcast_step(run, step, "waiting_hitl", {"conflict_id": run.conflict_id})
            await manager.broadcast("conflict_suggestion_ready", {
                "conflict_id": run.conflict_id,
                "workflow_run_id": run.id,
                "approval_status": "pending_approval",
            })
            return "pause_hitl"

        elif step_id == "commit_record":
            conflict = await db.get(ConflictEvent, run.conflict_id)
            if not conflict:
                raise ValueError("Conflict not found at commit step")
            if conflict.status != "resolved":
                if conflict.approval_status == "pending_approval":
                    await hitl_service.approve_conflict(db, run.conflict_id, user)
                    conflict = await db.get(ConflictEvent, run.conflict_id)
            stmt = select(CommitLog).where(
                CommitLog.file_path == conflict.file_path,
                CommitLog.had_conflict == True,  # noqa: E712
            ).order_by(CommitLog.created_at.desc()).limit(1)
            commit = (await db.execute(stmt)).scalars().first()
            if commit:
                ctx["commit_hash"] = commit.commit_hash
                run.context_json = json.dumps(ctx)

        elif step_id == "detect_anomaly":
            metrics = ctx.get("metrics") or {
                "service_name": "checkout-service",
                "response_time_ms": 3200,
                "error_rate_pct": 18.0,
                "db_pool_usage_pct": 72.0,
                "affected_users_pct": 12.0,
                "monitor_source": "workflow_orchestrator",
            }
            pipeline_result = await run_incident_pipeline(db, metrics)
            if not pipeline_result.get("anomaly_detected"):
                raise ValueError("No anomaly detected — cannot run incident workflow")
            run.incident_id = pipeline_result["incident_id"]
            ctx["incident_id"] = pipeline_result["incident_id"]
            ctx["pipeline_result"] = pipeline_result
            run.context_json = json.dumps(ctx)
            for sub_step in ("root_cause", "severity_classify", "tool_execute", "escalation", "coordinator_link", "notify_team"):
                await CoordinatorAgent.log_decision(
                    db, "Workflow Orchestrator", "aiops",
                    f"Incident pipeline sub-step '{sub_step}' completed for incident #{run.incident_id}.",
                    False, run.incident_id,
                )

        elif step_id in ("root_cause", "severity_classify", "tool_execute", "escalation", "notify_team"):
            if not run.incident_id:
                ctx.setdefault("note", "Handled by incident pipeline in detect_anomaly step")
                run.context_json = json.dumps(ctx)

        elif step_id == "coordinator_link":
            incident = await db.get(Incident, run.incident_id) if run.incident_id else None
            if incident and not incident.linked_commit_id:
                linked = await CoordinatorAgent.find_linked_commit(db, incident.service_name)
                if linked:
                    await CoordinatorAgent.link_incident_to_commit(db, incident, linked)
                    ctx["linked_commit_hash"] = linked.commit_hash
                    run.context_json = json.dumps(ctx)

        elif step_id == "incident_correlation":
            conflict = await db.get(ConflictEvent, run.conflict_id)
            if conflict and conflict.status == "resolved":
                stmt = select(Incident).where(
                    Incident.status.in_(["open", "escalated"]),
                    Incident.linked_commit_id.is_(None),
                ).order_by(Incident.detected_at.desc()).limit(1)
                incident = (await db.execute(stmt)).scalars().first()
                if incident:
                    stmt2 = select(CommitLog).where(
                        CommitLog.file_path == conflict.file_path,
                        CommitLog.had_conflict == True,  # noqa: E712
                    ).order_by(CommitLog.created_at.desc()).limit(1)
                    commit = (await db.execute(stmt2)).scalars().first()
                    if commit:
                        await CoordinatorAgent.link_incident_to_commit(db, incident, commit)
                        run.incident_id = incident.id
                        ctx["linked_incident_id"] = incident.id
                        ctx["linked_commit_hash"] = commit.commit_hash
                        run.context_json = json.dumps(ctx)

        elif step_id == "complete":
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            db.add(run)
            await _log_step(db, run, step, step_index, "completed", {"message": "Workflow finished"})
            await manager.broadcast("workflow_completed", {"run_id": run.id, "template_key": run.template_key})
            return "done"

        await _log_step(db, run, step, step_index, "completed")
        await _broadcast_step(run, step, "completed")
        return "continue"

    except Exception as exc:
        logger.warning(f"Workflow step {step_id} failed on run #{run.id}: {exc}")
        await _log_step(db, run, step, step_index, "failed", error=str(exc))
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = datetime.utcnow()
        db.add(run)
        await db.commit()
        await _broadcast_step(run, step, "failed", {"error": str(exc)})
        return "failed"


async def _advance_run(db: AsyncSession, run: WorkflowRun, user: User) -> WorkflowRun:
    steps = template_steps(run.template_key)
    while run.current_step_index < len(steps):
        step = steps[run.current_step_index]
        action = await _execute_step(db, run, user, step, run.current_step_index)
        if action == "pause_hitl":
            await db.refresh(run)
            return run
        if action == "failed":
            await db.refresh(run)
            return run
        if action == "done":
            await db.refresh(run)
            return run
        run.current_step_index += 1
        run.status = "running"
        run.updated_at = datetime.utcnow()
        db.add(run)
        await db.commit()
        await db.refresh(run)

    run.status = "completed"
    run.completed_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await manager.broadcast("workflow_completed", {"run_id": run.id, "template_key": run.template_key})
    return run


async def run_workflow_advance(db: AsyncSession, run: WorkflowRun, user: User) -> WorkflowRun:
    """Public entry for job queue worker."""
    return await _advance_run(db, run, user)


async def start_workflow(
    db: AsyncSession,
    user: User,
    template_key: str,
    context: dict | None = None,
) -> dict:
    definition = await db.scalar(
        select(WorkflowDefinition).where(WorkflowDefinition.template_key == template_key)
    )
    if not definition:
        raise ValueError(f"Workflow template '{template_key}' not found")

    ctx = context or {}
    conflict_id = ctx.get("conflict_id")
    incident_id = ctx.get("incident_id")

    initial_status = "queued" if settings.JOB_QUEUE_ENABLED else "running"
    run = WorkflowRun(
        definition_id=definition.id,
        template_key=template_key,
        status=initial_status,
        current_step_index=0,
        started_by_user_id=user.id,
        context_json=json.dumps(ctx),
        conflict_id=conflict_id,
        incident_id=incident_id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    db.add(WorkflowJob(
        run_id=run.id,
        step_index=0,
        job_type="execute_step",
        status="queued" if settings.JOB_QUEUE_ENABLED else "running",
        started_at=None if settings.JOB_QUEUE_ENABLED else datetime.utcnow(),
    ))
    await db.commit()

    await manager.broadcast("workflow_started", {
        "run_id": run.id,
        "template_key": template_key,
        "started_by": user.full_name,
        "queued": settings.JOB_QUEUE_ENABLED,
    })

    if settings.JOB_QUEUE_ENABLED:
        await job_queue_service.enqueue("workflow_start", {"run_id": run.id, "user_id": user.id})
        return _serialize_run(run, definition)

    run = await _advance_run(db, run, user)
    return _serialize_run(run, definition)


async def resume_workflow_internal(db: AsyncSession, user: User, run_id: int) -> WorkflowRun:
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise ValueError("Workflow run not found")
    if run.status not in ("waiting_hitl", "queued"):
        raise ValueError("Workflow is not waiting for human approval")

    conflict = await db.get(ConflictEvent, run.conflict_id) if run.conflict_id else None
    if conflict and conflict.approval_status != "approved":
        if conflict.approval_status == "pending_approval":
            await hitl_service.approve_conflict(db, run.conflict_id, user)

    run.status = "running"
    run.current_step_index += 1
    run.updated_at = datetime.utcnow()
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return await _advance_run(db, run, user)


async def resume_workflow(db: AsyncSession, user: User, run_id: int) -> dict:
    if settings.JOB_QUEUE_ENABLED:
        run = await db.get(WorkflowRun, run_id)
        if not run:
            raise ValueError("Workflow run not found")
        if run.status != "waiting_hitl":
            raise ValueError("Workflow is not waiting for human approval")
        run.status = "queued"
        run.updated_at = datetime.utcnow()
        db.add(run)
        await db.commit()
        await job_queue_service.enqueue("workflow_resume", {"run_id": run_id, "user_id": user.id})
        definition = await db.get(WorkflowDefinition, run.definition_id)
        return _serialize_run(run, definition)

    run = await resume_workflow_internal(db, user, run_id)
    definition = await db.get(WorkflowDefinition, run.definition_id)
    return _serialize_run(run, definition)


async def cancel_workflow(db: AsyncSession, user: User, run_id: int) -> dict:
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise ValueError("Workflow run not found")
    if run.status in ("completed", "cancelled"):
        raise ValueError(f"Cannot cancel workflow in status '{run.status}'")

    run.status = "cancelled"
    run.completed_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    db.add(run)
    await db.commit()
    await manager.broadcast("workflow_cancelled", {"run_id": run.id})
    definition = await db.get(WorkflowDefinition, run.definition_id)
    return _serialize_run(run, definition)


async def list_runs(
    db: AsyncSession,
    user: User,
    status: str | None = None,
    limit: int = 20,
) -> list[dict]:
    stmt = select(WorkflowRun).order_by(WorkflowRun.started_at.desc()).limit(min(limit, 50))
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    runs = (await db.execute(stmt)).scalars().all()
    out = []
    for run in runs:
        definition = await db.get(WorkflowDefinition, run.definition_id)
        out.append({**_serialize_run(run, definition), "started_by_user_id": run.started_by_user_id})
    return out


async def get_run(db: AsyncSession, run_id: int) -> dict:
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise ValueError("Workflow run not found")
    definition = await db.get(WorkflowDefinition, run.definition_id)
    return _serialize_run(run, definition)


async def get_timeline(db: AsyncSession, run_id: int) -> list[dict]:
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise ValueError("Workflow run not found")
    result = await db.execute(
        select(WorkflowStepLog)
        .where(WorkflowStepLog.run_id == run_id)
        .order_by(WorkflowStepLog.step_index, WorkflowStepLog.id)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "step_index": log.step_index,
            "step_id": log.step_id,
            "agent_name": log.agent_name,
            "module": log.module,
            "status": log.status,
            "output": _parse_json(log.output_json) if log.output_json else None,
            "error_message": log.error_message,
            "retry_count": log.retry_count,
            "started_at": utc_iso(log.started_at),
            "completed_at": utc_iso(log.completed_at),
        }
        for log in logs
    ]


async def get_workflow_stats(db: AsyncSession) -> dict:
    total = await db.scalar(select(func.count()).select_from(WorkflowRun)) or 0
    running = await db.scalar(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.status == "running")
    ) or 0
    waiting_hitl = await db.scalar(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.status == "waiting_hitl")
    ) or 0
    completed = await db.scalar(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.status == "completed")
    ) or 0
    failed = await db.scalar(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.status == "failed")
    ) or 0
    return {
        "total_runs": total,
        "running": running,
        "waiting_hitl": waiting_hitl,
        "completed": completed,
        "failed": failed,
    }
