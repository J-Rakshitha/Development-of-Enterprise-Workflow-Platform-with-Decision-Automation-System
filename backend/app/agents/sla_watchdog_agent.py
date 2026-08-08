"""Milestone 4 — SLA Watchdog Agent (background SLA breach detection)."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agents.aiops.escalation_agent import EscalationAgent
from app.models.incident import Incident


class SlaWatchdogAgent:
    @staticmethod
    async def find_breached_incidents(db: AsyncSession) -> list[Incident]:
        now = datetime.utcnow()
        stmt = select(Incident).where(
            Incident.status.in_(["open", "escalated"]),
            Incident.sla_deadline.isnot(None),
            Incident.sla_deadline < now,
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    def build_escalation(incident: Incident) -> dict:
        return EscalationAgent.build_escalation(
            incident.id,
            incident.severity or "P2",
            incident.root_cause or "SLA deadline exceeded",
        )
