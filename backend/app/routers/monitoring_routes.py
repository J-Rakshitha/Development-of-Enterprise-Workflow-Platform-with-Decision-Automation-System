"""
Monitoring API routes — Phase B + Milestone 4 uptime metrics
Prefix: /api/monitoring
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.monitoring import ServiceHealthSnapshot
from app.services.monitored_services_service import resolve_monitor_targets

router = APIRouter(prefix="/api/monitoring", tags=["Server Monitoring"])


@router.get("/status")
async def monitoring_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Latest health snapshot per monitored service (real probe data, not hardcoded)."""
    targets = await resolve_monitor_targets(db)
    services = []

    for target in targets:
        result = await db.execute(
            select(ServiceHealthSnapshot)
            .where(ServiceHealthSnapshot.service_name == target["name"])
            .order_by(ServiceHealthSnapshot.checked_at.desc())
            .limit(1)
        )
        snap = result.scalars().first()
        if snap:
            services.append({
                "service_name": snap.service_name,
                "url": snap.url,
                "status_code": snap.status_code,
                "response_time_ms": snap.response_time_ms,
                "error_rate_pct": snap.error_rate_pct,
                "healthy": snap.healthy,
                "checked_at": snap.checked_at,
            })
        else:
            services.append({
                "service_name": target["name"],
                "url": target["url"],
                "status_code": None,
                "response_time_ms": None,
                "error_rate_pct": None,
                "healthy": None,
                "checked_at": None,
            })

    return {
        "monitoring_enabled": settings.MONITORING_ENABLED,
        "interval_seconds": settings.MONITOR_INTERVAL_SECONDS,
        "services": services,
    }


@router.get("/history/{service_name}")
async def monitoring_history(
    service_name: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recent probe history for charts / debugging."""
    result = await db.execute(
        select(ServiceHealthSnapshot)
        .where(ServiceHealthSnapshot.service_name == service_name)
        .order_by(ServiceHealthSnapshot.checked_at.desc())
        .limit(min(limit, 100))
    )
    snaps = result.scalars().all()
    return [
        {
            "response_time_ms": s.response_time_ms,
            "status_code": s.status_code,
            "healthy": s.healthy,
            "checked_at": s.checked_at,
        }
        for s in snaps
    ]


@router.get("/uptime/{service_name}")
async def monitoring_uptime(
    service_name: str,
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Calculate real uptime % from probe history — not hardcoded."""
    since = datetime.utcnow() - timedelta(hours=min(hours, 168))
    result = await db.execute(
        select(ServiceHealthSnapshot)
        .where(
            ServiceHealthSnapshot.service_name == service_name,
            ServiceHealthSnapshot.checked_at >= since,
        )
        .order_by(ServiceHealthSnapshot.checked_at.desc())
    )
    snaps = result.scalars().all()
    if not snaps:
        return {"service_name": service_name, "uptime_pct": None, "samples": 0, "hours": hours}
    healthy_count = sum(1 for s in snaps if s.healthy)
    uptime_pct = round((healthy_count / len(snaps)) * 100, 2)
    avg_response = round(sum(s.response_time_ms or 0 for s in snaps) / len(snaps), 1)
    return {
        "service_name": service_name,
        "uptime_pct": uptime_pct,
        "samples": len(snaps),
        "hours": hours,
        "avg_response_time_ms": avg_response,
        "last_checked": snaps[0].checked_at,
    }


@router.get("/summary")
async def monitoring_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """All monitored services with latest status and 24h uptime."""
    targets = await resolve_monitor_targets(db)
    summary = []
    since = datetime.utcnow() - timedelta(hours=24)
    for target in targets:
        name = target["name"]
        latest = await db.execute(
            select(ServiceHealthSnapshot)
            .where(ServiceHealthSnapshot.service_name == name)
            .order_by(ServiceHealthSnapshot.checked_at.desc())
            .limit(1)
        )
        snap = latest.scalars().first()
        history = await db.execute(
            select(ServiceHealthSnapshot)
            .where(ServiceHealthSnapshot.service_name == name, ServiceHealthSnapshot.checked_at >= since)
        )
        snaps = history.scalars().all()
        uptime = round((sum(1 for s in snaps if s.healthy) / len(snaps)) * 100, 2) if snaps else None
        summary.append({
            "service_name": name,
            "url": target["url"],
            "healthy": snap.healthy if snap else None,
            "response_time_ms": snap.response_time_ms if snap else None,
            "status_code": snap.status_code if snap else None,
            "checked_at": snap.checked_at if snap else None,
            "uptime_24h_pct": uptime,
        })
    return {"services": summary, "monitoring_enabled": settings.MONITORING_ENABLED}
