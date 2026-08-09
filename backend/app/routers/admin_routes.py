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
from app.services.monitoring_scheduler import trigger_probe_now
from app.services.sla_watchdog_scheduler import _watchdog_task
from app.services import monitored_services_service as ms
from app.services.monitored_services_service import resolve_monitor_targets

router = APIRouter(prefix="/api/admin", tags=["Admin / Ops"])


class MonitoringConfigIn(BaseModel):
    interval_seconds: int | None = None


class MonitoredServiceIn(BaseModel):
    name: str
    url: str
    enabled: bool = True
    is_internal: bool = False


class MonitoredServiceUpdateIn(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None
    is_internal: bool | None = None


@router.get("/system-health")
async def admin_system_health(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    from app.agents.llm.llm_client import get_simulated_failure
    from app.services.monitoring_scheduler import _monitor_task
    from app.services.job_queue_service import get_queue_stats

    workflow_count = await db.scalar(select(func.count()).select_from(WorkflowRun)) or 0
    targets = await resolve_monitor_targets(db)
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
        "monitored_services": [t["name"] for t in targets],
        "job_queue": get_queue_stats(),
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
async def admin_monitoring_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    targets = await resolve_monitor_targets(db)
    return {
        "monitoring_enabled": settings.MONITORING_ENABLED,
        "interval_seconds": settings.MONITOR_INTERVAL_SECONDS,
        "targets": targets,
        "thresholds": {
            "response_time_ms": settings.MONITORING_RESPONSE_TIME_MS_THRESHOLD,
            "error_rate_pct": settings.MONITORING_ERROR_RATE_PCT_THRESHOLD,
            "db_pool_usage_pct": settings.MONITORING_DB_POOL_USAGE_PCT_THRESHOLD,
        },
    }


@router.get("/monitored-services")
async def list_monitored_services(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    rows = await ms.list_monitored_services(db)
    return [ms.serialize_service(r) for r in rows]


@router.post("/monitored-services")
async def create_monitored_service(
    payload: MonitoredServiceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    try:
        row = await ms.create_monitored_service(
            db,
            name=payload.name,
            url=payload.url,
            enabled=payload.enabled,
            is_internal=payload.is_internal,
        )
        return ms.serialize_service(row)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/monitored-services/{service_id}")
async def update_monitored_service(
    service_id: int,
    payload: MonitoredServiceUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    try:
        row = await ms.update_monitored_service(
            db,
            service_id,
            name=payload.name,
            url=payload.url,
            enabled=payload.enabled,
            is_internal=payload.is_internal,
        )
        return ms.serialize_service(row)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/monitored-services/{service_id}")
async def delete_monitored_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    try:
        await ms.delete_monitored_service(db, service_id)
        return {"success": True, "id": service_id}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
