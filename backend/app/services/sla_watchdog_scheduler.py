"""Milestone 4 — SLA Watchdog background scheduler."""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.agents.aiops.escalation_agent import EscalationAgent
from app.agents.coordinator_agent import CoordinatorAgent
from app.agents.notification_agent import NotificationAgent
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.incident import Incident
from app.routers.websocket_routes import manager

logger = logging.getLogger("sla_watchdog")

_watchdog_task: asyncio.Task | None = None
_escalated_ids: set[int] = set()
CHECK_INTERVAL_SECONDS = 60


async def _check_sla_breaches() -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        stmt = select(Incident).where(
            Incident.status.in_(["open", "escalated"]),
            Incident.sla_deadline.isnot(None),
            Incident.sla_deadline < now,
        )
        incidents = (await db.execute(stmt)).scalars().all()

        for incident in incidents:
            if incident.id in _escalated_ids:
                continue

            escalation = EscalationAgent.build_escalation(
                incident.id,
                incident.severity or "P2",
                incident.root_cause or "SLA breach — no root cause recorded",
            )
            incident.status = "escalated"
            incident.escalated_to = escalation["escalated_to"]
            db.add(incident)
            await db.commit()

            await CoordinatorAgent.log_decision(
                db,
                agent_name="SLA Watchdog Agent",
                module="aiops",
                decision_summary=(
                    f"SLA breach on incident #{incident.id} ({incident.service_name}) — "
                    f"deadline {incident.sla_deadline.isoformat()} passed. "
                    f"Auto-escalated to {escalation['escalated_to']}."
                ),
                used_llm=False,
                related_entity_id=incident.id,
            )

            await NotificationAgent.notify_incident_created(
                db,
                incident_id=incident.id,
                service_name=incident.service_name,
                severity=incident.severity or "P2",
                root_cause=f"SLA BREACH: {incident.root_cause or 'Deadline exceeded'}",
                status="escalated",
                sla_deadline=incident.sla_deadline.isoformat() if incident.sla_deadline else None,
                escalated_to=incident.escalated_to,
                triggered_by=incident.triggered_by,
            )

            await manager.broadcast("sla_breach", {
                "incident_id": incident.id,
                "service_name": incident.service_name,
                "severity": incident.severity,
                "escalated_to": incident.escalated_to,
                "sla_deadline": incident.sla_deadline.isoformat() if incident.sla_deadline else None,
            })

            _escalated_ids.add(incident.id)
            logger.info(f"SLA breach escalated incident #{incident.id}")


async def _watchdog_loop() -> None:
    logger.info(f"SLA Watchdog started (every {CHECK_INTERVAL_SECONDS}s)")
    await asyncio.sleep(15)
    while True:
        try:
            await _check_sla_breaches()
        except Exception as exc:
            logger.warning(f"SLA watchdog cycle error (non-fatal): {exc}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def start_sla_watchdog() -> None:
    global _watchdog_task
    if _watchdog_task and not _watchdog_task.done():
        return
    _watchdog_task = asyncio.create_task(_watchdog_loop())


async def stop_sla_watchdog() -> None:
    global _watchdog_task
    if _watchdog_task and not _watchdog_task.done():
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass
    _watchdog_task = None
