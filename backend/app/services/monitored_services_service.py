"""DB-backed monitored service targets with env fallback and admin CRUD helpers."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.monitoring import MonitoredService


def env_default_targets() -> list[dict]:
    """Legacy .env defaults — used when DB table is empty or for sync callers."""
    return [
        {
            "name": settings.MONITOR_BACKEND_NAME,
            "url": settings.MONITOR_BACKEND_URL,
            "internal": True,
        },
        {
            "name": settings.MONITOR_EXTERNAL_NAME,
            "url": settings.MONITOR_EXTERNAL_URL,
            "internal": False,
        },
    ]


def get_monitor_targets() -> list[dict]:
    """Sync fallback for MCP and other non-async callers."""
    return env_default_targets()


async def resolve_monitor_targets(db: AsyncSession) -> list[dict]:
    """Enabled targets from DB, falling back to env defaults when table is empty."""
    result = await db.execute(
        select(MonitoredService)
        .where(MonitoredService.enabled == True)  # noqa: E712
        .order_by(MonitoredService.id)
    )
    rows = result.scalars().all()
    if not rows:
        return env_default_targets()
    return [
        {"name": row.name, "url": row.url, "internal": row.is_internal}
        for row in rows
    ]


async def seed_default_monitored_services(db: AsyncSession) -> None:
    """Seed env defaults once so admin UI can edit without restart."""
    count = await db.scalar(select(func.count()).select_from(MonitoredService)) or 0
    if count > 0:
        return
    for target in env_default_targets():
        db.add(
            MonitoredService(
                name=target["name"],
                url=target["url"],
                enabled=True,
                is_internal=target["internal"],
            )
        )
    await db.commit()


async def list_monitored_services(db: AsyncSession) -> list[MonitoredService]:
    result = await db.execute(select(MonitoredService).order_by(MonitoredService.id))
    return list(result.scalars().all())


def serialize_service(row: MonitoredService) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "enabled": row.enabled,
        "is_internal": row.is_internal,
        "created_at": row.created_at,
    }


async def create_monitored_service(
    db: AsyncSession,
    *,
    name: str,
    url: str,
    enabled: bool = True,
    is_internal: bool = False,
) -> MonitoredService:
    existing = await db.execute(select(MonitoredService).where(MonitoredService.name == name.strip()))
    if existing.scalars().first():
        raise ValueError(f"Service name '{name}' already exists.")
    row = MonitoredService(
        name=name.strip(),
        url=url.strip(),
        enabled=enabled,
        is_internal=is_internal,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_monitored_service(
    db: AsyncSession,
    service_id: int,
    *,
    name: str | None = None,
    url: str | None = None,
    enabled: bool | None = None,
    is_internal: bool | None = None,
) -> MonitoredService:
    row = await db.get(MonitoredService, service_id)
    if not row:
        raise LookupError("Monitored service not found.")
    if name is not None:
        clash = await db.execute(
            select(MonitoredService).where(
                MonitoredService.name == name.strip(),
                MonitoredService.id != service_id,
            )
        )
        if clash.scalars().first():
            raise ValueError(f"Service name '{name}' already exists.")
        row.name = name.strip()
    if url is not None:
        row.url = url.strip()
    if enabled is not None:
        row.enabled = enabled
    if is_internal is not None:
        row.is_internal = is_internal
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_monitored_service(db: AsyncSession, service_id: int) -> None:
    row = await db.get(MonitoredService, service_id)
    if not row:
        raise LookupError("Monitored service not found.")
    await db.delete(row)
    await db.commit()
