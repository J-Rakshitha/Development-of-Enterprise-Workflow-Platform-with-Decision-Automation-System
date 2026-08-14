"""
Shared incident pipeline — used by REST ingest, simulate, and background monitor.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.agents.aiops.monitoring_agent import MonitoringAgent
from app.agents.aiops.root_cause_agent import RootCauseAgent
from app.agents.aiops.severity_agent import SeverityAgent
from app.agents.aiops.escalation_agent import EscalationAgent
from app.agents.aiops.external_lookup_agent import ExternalLookupAgent
from app.agents.coordinator_agent import CoordinatorAgent
from app.agents.notification_agent import NotificationAgent
from app.agents.tools.tool_executor_agent import ToolExecutorAgent
from app.agents.tools import tool_handlers  # noqa: F401
from app.agents.aiops.server_monitor_agent import ServerMonitorAgent
from app.services.monitored_services_service import resolve_monitor_targets


async def confirm_service_recovered(db: AsyncSession, service_name: str) -> tuple[bool, dict]:
    """Re-probe a registered URL after remediation. Never trust simulated tool success alone."""
    targets = await resolve_monitor_targets(db)
    keyword = (service_name or "").lower().replace("-service", "").replace("_", "")
    target = None
    for item in targets:
        name = (item.get("name") or "").lower().replace("_", "").replace("-", "")
        if keyword and (keyword in name or name in keyword):
            target = item
            break
    if target is None:
        # Incident service names may not match monitor probe targets — probe a registered health URL
        target = next((item for item in targets if item.get("internal")), None) or (
            targets[0] if targets else None
        )
    url = (target or {}).get("url") or ""
    if not url:
        return False, {"healthy": False, "reason": "no_monitor_target"}

    probe = await ServerMonitorAgent.probe(
        (target or {}).get("name") or service_name,
        url,
        timeout=8.0,
    )
    recovered = MonitoringAgent.is_recovered(probe)
    probe["recovered"] = recovered
    return recovered, probe


async def run_incident_pipeline(db: AsyncSession, metrics: dict) -> dict:
    """
    Monitoring -> Root Cause -> Severity -> Tool Selection -> Escalation -> Coordinator link.
    Same person + service: refresh their existing card with THIS run's live data.
    Different person: creates their own new incident card.
    """
    anomaly = MonitoringAgent.detect_anomaly(metrics)
    if not anomaly:
        return {"anomaly_detected": False}

    incident_source = metrics.get("incident_source") or metrics.get("monitor_source") or "ingest"
    if incident_source == "background_monitor":
        incident_source = "monitoring"
    triggered_by = str(metrics.get("triggered_by") or "System").strip() or "System"

    # Always create a new incident row — each trigger keeps history (no upsert override)
    incident = Incident(
        title=f"Anomaly detected on {anomaly['service_name']}",
        service_name=anomaly["service_name"],
        detected_at=datetime.utcnow(),
        status="open",
        source=incident_source,
        triggered_by=triggered_by,
    )
    db.add(incident)
    await db.commit()
    await db.refresh(incident)

    await CoordinatorAgent.log_decision(
        db=db,
        agent_name="Monitoring Agent",
        module="aiops",
        decision_summary=(
            f"Anomaly detected on {anomaly['service_name']}: "
            f"{anomaly['error_signature']} "
            f"(error_rate={anomaly['error_rate_pct']}%, "
            f"affected_users={anomaly['affected_users_pct']}%) "
            f"by {triggered_by}"
        ),
        used_llm=False,
        related_entity_id=incident.id,
    )

    root_cause_result = await RootCauseAgent.analyze(
        db,
        anomaly["service_name"],
        anomaly["error_signature"],
        anomaly["raw_metrics"],
        triggered_by=triggered_by,
    )
    incident.root_cause = root_cause_result["root_cause"]

    search_terms = anomaly["error_signature"].replace("_", " ")
    from app.services.demo_filters import sanitize_external_references

    external_refs = sanitize_external_references(
        await ExternalLookupAgent.find_related_issues(search_terms)
    )
    incident.external_references = json.dumps(external_refs)
    await CoordinatorAgent.log_decision(
        db=db,
        agent_name="External Lookup Agent",
        module="aiops",
        decision_summary=(
            f"Queried GitHub's public issue tracker for '{search_terms}' — "
            f"found {len(external_refs)} related reference(s)."
        ),
        used_llm=False,
    )

    severity = SeverityAgent.classify(anomaly["error_rate_pct"], anomaly["affected_users_pct"])
    incident.severity = severity
    sla_minutes = SeverityAgent.sla_minutes_for(severity)
    incident.sla_minutes = sla_minutes
    incident.sla_deadline = datetime.utcnow() + timedelta(minutes=sla_minutes)

    await CoordinatorAgent.log_decision(
        db=db,
        agent_name="Severity Agent",
        module="aiops",
        decision_summary=(
            f"Classified incident on {anomaly['service_name']} as {severity} "
            f"(SLA: {SeverityAgent.sla_minutes_for(severity)} min)"
        ),
        used_llm=False,
        related_entity_id=incident.id,
    )

    situation = (
        f"Incident on {anomaly['service_name']}, severity {severity}: "
        f"{root_cause_result['root_cause']}"
    )
    tool_result = await ToolExecutorAgent.select_and_execute(
        db, situation,
        incident_id=incident.id,
        severity=severity,
        reason=root_cause_result["root_cause"],
    )
    action_taken = tool_result["tool_name"]
    tool_ok = (
        tool_result["tool_name"] in ("restart_service", "clear_cache") and tool_result["success"]
    )

    recovered = False
    probe = {}
    if tool_ok:
        recovered, probe = await confirm_service_recovered(db, anomaly["service_name"])
        await CoordinatorAgent.log_decision(
            db=db,
            agent_name="Monitoring Agent",
            module="aiops",
            decision_summary=(
                f"Post-remediation probe of {probe.get('url') or anomaly['service_name']}: "
                f"healthy={probe.get('healthy')}, error_rate={probe.get('error_rate_pct')}%, "
                f"db_pool={probe.get('db_pool_usage_pct')}%, latency={probe.get('response_time_ms')}ms "
                f"— recovered={recovered}."
            ),
            used_llm=False,
            related_entity_id=incident.id,
        )

    if tool_ok and recovered:
        incident.status = "auto_resolved"
        incident.resolved_at = datetime.utcnow()
        incident.mttr_seconds = int((incident.resolved_at - incident.detected_at).total_seconds())
        incident.escalated_to = None
    else:
        incident.status = "escalated"
        incident.resolved_at = None
        incident.mttr_seconds = None

    db.add(incident)
    await db.commit()
    await db.refresh(incident)

    escalation = None
    if incident.status != "auto_resolved":
        escalation = EscalationAgent.build_escalation(
            incident.id, severity, root_cause_result["root_cause"]
        )
        incident.escalated_to = escalation["escalated_to"]
        db.add(incident)
        await db.commit()
        await db.refresh(incident)

    linked_commit = await CoordinatorAgent.find_linked_commit(db, anomaly["service_name"])
    linked_commit_info = None
    if linked_commit:
        await CoordinatorAgent.link_incident_to_commit(db, incident, linked_commit)
        linked_commit_info = {
            "commit_hash": linked_commit.commit_hash,
            "file_path": linked_commit.file_path,
            "message": linked_commit.message,
            "had_conflict": linked_commit.had_conflict,
        }
        await CoordinatorAgent.log_decision(
            db=db,
            agent_name="Coordinator Agent",
            module="aiops",
            decision_summary=(
                f"Linked incident #{incident.id} to commit {linked_commit.commit_hash} "
                f"({linked_commit.file_path}) — cross-module Dev→Production correlation."
            ),
            used_llm=False,
            related_entity_id=incident.id,
        )

    await NotificationAgent.notify_incident_created(
        db,
        incident_id=incident.id,
        service_name=anomaly["service_name"],
        severity=severity,
        root_cause=incident.root_cause or "",
        status=incident.status,
        sla_deadline=incident.sla_deadline.isoformat() if incident.sla_deadline else None,
        escalated_to=incident.escalated_to,
        triggered_by=incident.triggered_by,
    )

    return {
        "anomaly_detected": True,
        "incident_id": incident.id,
        "severity": severity,
        "root_cause": incident.root_cause,
        "action_taken": action_taken,
        "tool_selection_used_llm": tool_result["used_llm_selection"],
        "status": incident.status,
        "escalation": escalation,
        "linked_commit_id": incident.linked_commit_id,
        "linked_commit": linked_commit_info,
        "external_references": external_refs,
        "source": incident.source,
        "triggered_by": incident.triggered_by,
        "recovery_probe": {
            "url": probe.get("url"),
            "healthy": probe.get("healthy"),
            "error_rate_pct": probe.get("error_rate_pct"),
            "db_pool_usage_pct": probe.get("db_pool_usage_pct"),
            "response_time_ms": probe.get("response_time_ms"),
            "recovered": recovered,
        } if probe else None,
    }
