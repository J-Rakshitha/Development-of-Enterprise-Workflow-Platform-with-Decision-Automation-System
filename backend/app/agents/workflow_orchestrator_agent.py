"""Milestone 4 — Workflow Orchestrator Agent (thin facade)."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import workflow_orchestrator_service as engine


class WorkflowOrchestratorAgent:
    @staticmethod
    async def start(db: AsyncSession, user: User, template_key: str, context: dict | None = None) -> dict:
        return await engine.start_workflow(db, user, template_key, context)

    @staticmethod
    async def resume(db: AsyncSession, user: User, run_id: int) -> dict:
        return await engine.resume_workflow(db, user, run_id)

    @staticmethod
    async def stats(db: AsyncSession) -> dict:
        return await engine.get_workflow_stats(db)
