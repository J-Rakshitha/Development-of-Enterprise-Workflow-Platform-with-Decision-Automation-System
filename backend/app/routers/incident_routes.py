"""
AIOps Incident Response Module API routes.
Prefix: /api/incidents
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import simulate_endpoints_enabled
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas import MetricsSnapshotIn
from app.models.incident import Incident
from app.models.dev_collab import CommitLog
from app.models.user import User
from app.services.incident_pipeline import run_incident_pipeline
from app.services.synthetic_data_generator import random_metrics_snapshot
from app.routers.websocket_routes import manager

router = APIRouter(prefix="/api/incidents", tags=["AIOps Incident Response"])


@router.post("/ingest-metrics")
async def ingest_metrics(
    payload: MetricsSnapshotIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Feed a real metrics snapshot through the full agent pipeline."""
    metrics = payload.model_dump()
    if user:
        metrics["triggered_by"] = user.full_name
    result = await run_incident_pipeline(db, metrics)
    if result.get("anomaly_detected"):
        await manager.broadcast("incident_created", result)
    return result


@router.post("/simulate")
async def simulate_incident(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Demo one-click scenario — disabled in production (ENV=production)."""
    if not simulate_endpoints_enabled():
        raise HTTPException(status_code=403, detail="Simulate endpoints are disabled in production.")
    metrics = random_metrics_snapshot(force_anomaly=True)
    if user:
        metrics["triggered_by"] = user.full_name
    result = await run_incident_pipeline(db, metrics)
    if result.get("anomaly_detected"):
        await manager.broadcast("incident_created", result)
    return result


@router.get("/")
async def list_incidents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Incident).order_by(Incident.detected_at.desc()))
    incidents = result.scalars().all()

    output = []
    for i in incidents:
        linked_commit = None
        if i.linked_commit_id:
            commit = await db.get(CommitLog, i.linked_commit_id)
            if commit:
                linked_commit = {
                    "commit_hash": commit.commit_hash,
                    "file_path": commit.file_path,
                    "message": commit.message,
                    "had_conflict": commit.had_conflict,
                }
        output.append({
            "id": i.id, "title": i.title, "service_name": i.service_name,
            "severity": i.severity, "status": i.status, "root_cause": i.root_cause,
            "detected_at": i.detected_at, "resolved_at": i.resolved_at,
            "mttr_seconds": i.mttr_seconds, "linked_commit_id": i.linked_commit_id,
            "linked_commit": linked_commit,
            "external_references": json.loads(i.external_references) if i.external_references else [],
            "sla_minutes": i.sla_minutes,
            "sla_deadline": i.sla_deadline,
            "escalated_to": i.escalated_to,
        })
    return output
