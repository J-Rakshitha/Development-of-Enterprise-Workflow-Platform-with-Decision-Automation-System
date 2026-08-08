"""Milestone 4 — Workflow orchestration API."""
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import workflow_orchestrator_service as wf

router = APIRouter(prefix="/api/workflows", tags=["Workflow Orchestration"])


class StartWorkflowIn(BaseModel):
    template_key: str
    context: dict | None = None


@router.get("/definitions")
async def list_workflow_definitions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await wf.list_definitions(db)


@router.post("/start")
async def start_workflow(
    payload: StartWorkflowIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await wf.start_workflow(db, user, payload.template_key, payload.context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs")
async def list_workflow_runs(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await wf.list_runs(db, user, status=status, limit=limit)


@router.get("/stats")
async def workflow_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await wf.get_workflow_stats(db)


@router.get("/runs/{run_id}")
async def get_workflow_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await wf.get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/timeline")
async def get_workflow_timeline(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await wf.get_timeline(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/resume")
async def resume_workflow(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await wf.resume_workflow(db, user, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
async def cancel_workflow(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await wf.cancel_workflow(db, user, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
