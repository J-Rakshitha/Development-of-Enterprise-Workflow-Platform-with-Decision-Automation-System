"""Milestone 4 — Admin / Ops API."""
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_admin_user
from app.models.user import User
from app.models.workflow import ConflictActionLog as HITLLog
from app.models.dev_collab import ConflictEvent
from app.models.workflow_engine import WorkflowRun
from app.services.monitoring_scheduler import get_monitor_targets, trigger_probe_now
from app.services.sla_watchdog_scheduler import _watchdog_task

router = APIRouter(prefix="/api/admin", tags=["Admin / Ops"])


class MonitoringConfigIn(BaseModel):
    interval_seconds: int | None = None


@router.get("/system-health")
async def admin_system_health(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    from app.agents.llm.llm_client import get_simulated_failure
    from app.services.monitoring_scheduler import _monitor_task

    workflow_count = await db.scalar(select(func.count()).select_from(WorkflowRun)) or 0
    return {
        "app": settings.APP_NAME,
        "env": settings.ENV,
        "database": "connected",
        "monitoring_enabled": settings.MONITORING_ENABLED,
        "monitoring_scheduler_running": _monitor_task is not None and not _monitor_task.done(),
        "sla_watchdog_running": _watchdog_task is not None and not _watchdog_task.done(),
        "llm_enabled": settings.LLM_ENABLED,
        "llm_simulated_failure": get_simulated_failure(),
        "workflow_runs_total": workflow_count,
        "monitored_services": [t["name"] for t in get_monitor_targets()],
    }


@router.get("/users/activity")
async def admin_users_activity(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    hitl_actions = await db.scalar(select(func.count()).select_from(HITLLog)) or 0
    conflicts = await db.scalar(select(func.count()).select_from(ConflictEvent)) or 0
    users = (await db.execute(select(User))).scalars().all()
    return {
        "total_users": len(users),
        "hitl_actions_logged": hitl_actions,
        "conflicts_total": conflicts,
        "users": [
            {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role}
            for u in users
        ],
    }


@router.post("/monitoring/trigger-probe")
async def admin_trigger_probe(user: User = Depends(get_admin_user)):
    try:
        result = await trigger_probe_now()
        return {"success": True, "probes": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/monitoring/config")
async def admin_monitoring_config(user: User = Depends(get_admin_user)):
    return {
        "monitoring_enabled": settings.MONITORING_ENABLED,
        "interval_seconds": settings.MONITOR_INTERVAL_SECONDS,
        "targets": get_monitor_targets(),
        "thresholds": {
            "response_time_ms": settings.MONITORING_RESPONSE_TIME_MS_THRESHOLD,
            "error_rate_pct": settings.MONITORING_ERROR_RATE_PCT_THRESHOLD,
            "db_pool_usage_pct": settings.MONITORING_DB_POOL_USAGE_PCT_THRESHOLD,
        },
    }
