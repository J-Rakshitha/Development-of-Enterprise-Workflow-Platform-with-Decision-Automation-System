"""
AIOps Incident Response Module API routes.
Prefix: /api/incidents
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import simulate_endpoints_enabled, settings
from app.core.database import get_db
from app.core.datetime_utils import utc_iso
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas import MetricsSnapshotIn
from app.models.incident import Incident
from app.models.dev_collab import CommitLog
from app.services.incident_pipeline import run_incident_pipeline
from app.services.synthetic_data_generator import random_metrics_snapshot
from app.services.demo_filters import (
    is_demo_incident,
    sanitize_escalated_to,
    sanitize_external_references,
    sanitize_root_cause_for_ui,
    visible_feed_incidents,
    visible_linked_commit,
)
from app.services.metrics_webhook_service import MetricsWebhookService
from app.services.monitored_services_service import resolve_monitor_targets
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
    metrics["incident_source"] = "ingest"
    # Always the signed-in user who clicked Send Real Test Metrics (never a static name)
    metrics["triggered_by"] = (
        ((user.full_name or "").strip() if user else "")
        or ((user.email.split("@")[0] if user and user.email else "") or "API")
    )
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
    metrics["incident_source"] = "simulate"
    metrics["triggered_by"] = user.full_name if user else "Simulate"
    result = await run_incident_pipeline(db, metrics)
    if result.get("anomaly_detected"):
        await manager.broadcast("incident_created", result)
    return result


@router.get("/observability/status")
async def observability_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Observability integration status — webhook URL, monitoring, registered services."""
    targets = await resolve_monitor_targets(db)
    return {
        "webhook_url": MetricsWebhookService.webhook_url(),
        "webhook_secret_configured": bool((settings.METRICS_WEBHOOK_SECRET or "").strip()),
        "monitoring_enabled": settings.MONITORING_ENABLED,
        "monitor_interval_seconds": settings.MONITOR_INTERVAL_SECONDS,
        "registered_services": len(targets),
        "services": [{"name": t["name"], "url": t["url"]} for t in targets],
    }


@router.post("/alert-webhook")
async def alert_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Public observability alert webhook — Grafana/Prometheus POST here.
    Verify X-Metrics-Webhook-Secret matches METRICS_WEBHOOK_SECRET in .env.
    """
    body = await request.body()
    secret = MetricsWebhookService.secret_header_from_request(request)
    if not MetricsWebhookService.verify_secret(secret):
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid metrics webhook secret. "
                "Set X-Metrics-Webhook-Secret to match METRICS_WEBHOOK_SECRET in backend/.env."
            ),
        )

    if not body or not body.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "Empty body. In Postman: Body → raw → JSON, then paste: "
                '{"service_name":"checkout-service","response_time_ms":8500,'
                '"error_rate_pct":75,"db_pool_usage_pct":92,"affected_users_pct":80}'
            ),
        )

    try:
        payload = MetricsWebhookService.parse_payload(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid JSON: {exc}. Body must be raw JSON (not form-data). Example: "
                '{"service_name":"checkout-service","response_time_ms":8500,'
                '"error_rate_pct":75,"db_pool_usage_pct":92,"affected_users_pct":80}'
            ),
        ) from exc

    metrics = MetricsWebhookService.normalize_metrics(payload)
    if not metrics:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not parse metrics. Required field: service_name. "
                "Also send response_time_ms, error_rate_pct, db_pool_usage_pct, affected_users_pct. "
                f"Received keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
            ),
        )

    metrics["incident_source"] = "webhook"
    metrics["triggered_by"] = payload.get("triggered_by") or "Grafana Alert"

    result = await run_incident_pipeline(db, metrics)
    if result.get("anomaly_detected"):
        await manager.broadcast("incident_created", result)
    return {"processed": True, **result}


@router.get("/alert-webhook")
async def alert_webhook_info():
    """Browser-friendly info — external systems must POST alerts here."""
    return {
        "message": "Observability alert webhook is active. Grafana/Prometheus must POST JSON here.",
        "webhook_url": MetricsWebhookService.webhook_url(),
        "secret_configured": bool((settings.METRICS_WEBHOOK_SECRET or "").strip()),
        "expected_header": "X-Metrics-Webhook-Secret",
    }


@router.get("/")
async def list_incidents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Incident).order_by(Incident.detected_at.desc()))
    incidents = result.scalars().all()

    output = []
    for i in incidents:
        if await is_demo_incident(db, i):
            continue
        linked_commit = None
        if i.linked_commit_id:
            commit = await db.get(CommitLog, i.linked_commit_id)
            linked_commit = await visible_linked_commit(db, commit, service_name=i.service_name)
        output.append({
            "id": i.id, "title": i.title, "service_name": i.service_name,
            "severity": i.severity, "status": i.status,
            "root_cause": sanitize_root_cause_for_ui(i.root_cause),
            "detected_at": utc_iso(i.detected_at), "resolved_at": utc_iso(i.resolved_at),
            "mttr_seconds": i.mttr_seconds,
            "linked_commit_id": i.linked_commit_id if linked_commit else None,
            "linked_commit": linked_commit,
            "external_references": sanitize_external_references(
                json.loads(i.external_references) if i.external_references else []
            ),
            "sla_minutes": i.sla_minutes,
            "sla_deadline": utc_iso(i.sla_deadline),
            "escalated_to": sanitize_escalated_to(i.escalated_to),
            "source": i.source,
            "triggered_by": i.triggered_by,
        })
    # Recent enterprise AIOps cards (history kept per trigger); stale leftover rows stay in DB
    return visible_feed_incidents(output)
