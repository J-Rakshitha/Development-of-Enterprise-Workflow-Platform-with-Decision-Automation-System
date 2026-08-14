"""
Coordinator Agent (Common Core)
================================
The central "brain" of the whole engine. Both modules (Dev-Collaboration
and AIOps) report their events here. It:
  1. Logs every decision made by any agent (explainable-AI trail)
  2. Performs the cross-module "Linked Incidents" correlation —
     connecting a production incident back to a recent risky commit/conflict.
"""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import AgentDecisionLog, Incident
from app.models.dev_collab import CommitLog


class CoordinatorAgent:

    @staticmethod
    async def log_decision(
        db: AsyncSession,
        agent_name: str,
        module: str,
        decision_summary: str,
        used_llm: bool,
        related_entity_id: int | None = None,
    ) -> AgentDecisionLog:
        entry = AgentDecisionLog(
            agent_name=agent_name,
            module=module,
            related_entity_id=related_entity_id,
            decision_summary=decision_summary,
            used_llm=used_llm,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry

    @staticmethod
    def commit_matches_service(service_hint: str | None, file_path: str | None) -> bool:
        """True only when commit file name shares a keyword with the affected service."""
        if not service_hint or not file_path:
            return False
        service_keyword = (
            service_hint.lower()
            .replace("-service", "")
            .replace("_service", "")
            .replace("-", "")
            .replace("_", "")
            .strip()
        )
        base = file_path.replace("\\", "/").split("/")[-1]
        file_keyword = base.split(".")[0].lower().replace("_", "").replace("-", "").strip()
        if not service_keyword or not file_keyword:
            return False
        return service_keyword in file_keyword or file_keyword in service_keyword

    @staticmethod
    async def find_linked_commit(db: AsyncSession, service_hint: str, window_hours: int = 48) -> CommitLog | None:
        """
        Cross-module correlation: link an incident only when a recent commit
        file clearly matches the affected service (e.g. checkout.py ↔ checkout-service).

        No weak fallback to "any recent conflict" — that produced false links
        (payment-service → unrelated PR merge) and looked like demo noise.
        """
        since = datetime.utcnow() - timedelta(hours=window_hours)
        stmt = select(CommitLog).where(CommitLog.created_at >= since).order_by(CommitLog.created_at.desc())
        result = await db.execute(stmt)
        commits = result.scalars().all()
        if not commits:
            return None

        from app.services.demo_filters import is_demo_commit_hash

        # Skip leftover seed_full_demo commits so real incidents are not falsely linked
        commits = [c for c in commits if not is_demo_commit_hash(c.commit_hash)]
        if not commits:
            return None

        for commit in commits:
            if CoordinatorAgent.commit_matches_service(service_hint, commit.file_path):
                return commit

        return None

    @staticmethod
    async def link_incident_to_commit(db: AsyncSession, incident: Incident, commit: CommitLog) -> None:
        incident.linked_commit_id = commit.id
        db.add(incident)
        await db.commit()
