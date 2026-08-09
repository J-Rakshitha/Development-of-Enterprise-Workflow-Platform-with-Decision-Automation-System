"""
Background monitoring scheduler — Phase B
==========================================
Polls configured real URLs on an interval, persists snapshots, broadcasts
live updates over WebSocket, and triggers the incident pipeline on new
anomalies (with cooldown to avoid spam).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.monitored_services_service import resolve_monitor_targets
from app.models.monitoring import ServiceHealthSnapshot
from app.agents.aiops.server_monitor_agent import ServerMonitorAgent
from app.agents.aiops.monitoring_agent import MonitoringAgent
from app.agents.coordinator_agent import CoordinatorAgent
from app.services.incident_pipeline import run_incident_pipeline
from app.routers.websocket_routes import manager

logger = logging.getLogger("monitoring_scheduler")

_monitor_task: asyncio.Task | None = None
_last_healthy: dict[str, bool] = {}
_last_incident_at: dict[str, datetime] = {}
_failure_streak: dict[str, int] = {}
INCIDENT_COOLDOWN = timedelta(minutes=5)
FAILURES_BEFORE_INCIDENT = 2


def get_monitor_targets() -> list[dict]:
    """Sync env fallback — prefer resolve_monitor_targets(db) in async code paths."""
    from app.services.monitored_services_service import env_default_targets

    return env_default_targets()


def _is_own_backend(url: str) -> bool:
    return "127.0.0.1" in url or "localhost" in url


async def _probe_target(target: dict) -> dict:
    """Probe a target — internal check for own backend, HTTP for external services."""
    if target.get("internal") or _is_own_backend(target["url"]):
        return ServerMonitorAgent.probe_internal(target["name"], target["url"])
    # Run external HTTP probe in a thread so slow networks never block the event loop.
    return await asyncio.to_thread(
        _probe_external_sync, target["name"], target["url"]
    )


def _probe_external_sync(service_name: str, url: str) -> dict:
    import httpx

    start = __import__("time").perf_counter()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
        elapsed_ms = int((__import__("time").perf_counter() - start) * 1000)
        healthy = resp.status_code < 400 and elapsed_ms < 2000
        return {
            "service_name": service_name,
            "url": url,
            "status_code": resp.status_code,
            "response_time_ms": elapsed_ms,
            "error_rate_pct": 0.0 if resp.status_code < 400 else 100.0,
            "db_pool_usage_pct": 0.0,
            "affected_users_pct": 100.0 if resp.status_code >= 500 else 0.0,
            "healthy": healthy,
            "probe_type": "external",
        }
    except httpx.RequestError as exc:
        logger.debug(f"External probe failed for {service_name}: {type(exc).__name__}")
        return {
            "service_name": service_name,
            "url": url,
            "status_code": 0,
            "response_time_ms": int((__import__("time").perf_counter() - start) * 1000),
            "error_rate_pct": 100.0,
            "db_pool_usage_pct": 0.0,
            "affected_users_pct": 100.0,
            "healthy": False,
            "probe_type": "external",
        }


async def _save_snapshot(db, probe: dict) -> ServiceHealthSnapshot:
    snap = ServiceHealthSnapshot(
        service_name=probe["service_name"],
        url=probe["url"],
        status_code=probe["status_code"],
        response_time_ms=probe["response_time_ms"],
        error_rate_pct=probe["error_rate_pct"],
        healthy=probe["healthy"],
        checked_at=datetime.utcnow(),
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap


async def _run_probe_cycle() -> None:
    async with AsyncSessionLocal() as db:
        targets = await resolve_monitor_targets(db)
        for target in targets:
            probe = await _probe_target(target)
            snap = await _save_snapshot(db, probe)

            await manager.broadcast("service_health_update", {
                "service_name": probe["service_name"],
                "url": probe["url"],
                "status_code": probe["status_code"],
                "response_time_ms": probe["response_time_ms"],
                "healthy": probe["healthy"],
                "checked_at": snap.checked_at.isoformat(),
            })

            metrics = {
                "service_name": probe["service_name"],
                "response_time_ms": probe["response_time_ms"],
                "error_rate_pct": probe["error_rate_pct"],
                "db_pool_usage_pct": probe.get("db_pool_usage_pct", 0),
                "affected_users_pct": probe.get("affected_users_pct", 0),
                "monitor_source": "background_monitor",
            }

            is_healthy = probe["healthy"] and MonitoringAgent.detect_anomaly(metrics) is None
            name = probe["service_name"]

            if is_healthy:
                _failure_streak[name] = 0
                _last_healthy[name] = True
                continue

            _failure_streak[name] = _failure_streak.get(name, 0) + 1
            was_healthy = _last_healthy.get(name, True)
            _last_healthy[name] = False

            if not was_healthy or _failure_streak[name] < FAILURES_BEFORE_INCIDENT:
                continue

            last_at = _last_incident_at.get(name)
            if last_at and datetime.utcnow() - last_at < INCIDENT_COOLDOWN:
                continue

            result = await run_incident_pipeline(db, metrics)
            if result.get("anomaly_detected"):
                _last_incident_at[name] = datetime.utcnow()
                _failure_streak[name] = 0
                await CoordinatorAgent.log_decision(
                    db=db,
                    agent_name="Server Monitor Agent",
                    module="aiops",
                    decision_summary=(
                        f"Background probe detected anomaly on {name} "
                        f"({probe['url']}) — HTTP {probe['status_code']}, "
                        f"{probe['response_time_ms']}ms."
                    ),
                    used_llm=False,
                    related_entity_id=result.get("incident_id"),
                )
                await manager.broadcast("incident_created", result)


async def _monitor_loop() -> None:
    logger.info(
        f"Background monitoring started (every {settings.MONITOR_INTERVAL_SECONDS}s) — "
        f"targets: {[t['name'] for t in get_monitor_targets()]}"
    )
    # Let uvicorn finish startup before the first probe cycle.
    await asyncio.sleep(10)
    while True:
        try:
            await _run_probe_cycle()
        except Exception as exc:
            logger.warning(f"Monitor cycle error (non-fatal): {exc}")
        await asyncio.sleep(settings.MONITOR_INTERVAL_SECONDS)


async def start_monitoring() -> None:
    global _monitor_task
    if not settings.MONITORING_ENABLED:
        logger.info("Background monitoring disabled (MONITORING_ENABLED=False).")
        return
    if _monitor_task and not _monitor_task.done():
        return
    _monitor_task = asyncio.create_task(_monitor_loop())


async def trigger_probe_now() -> list[dict]:
    """Manual probe — used by admin API for on-demand health checks."""
    results = []
    async with AsyncSessionLocal() as db:
        targets = await resolve_monitor_targets(db)
        for target in targets:
            probe = await _probe_target(target)
            snap = await _save_snapshot(db, probe)
            await manager.broadcast("service_health_update", {
                "service_name": probe["service_name"],
                "url": probe["url"],
                "status_code": probe["status_code"],
                "response_time_ms": probe["response_time_ms"],
                "healthy": probe["healthy"],
                "checked_at": snap.checked_at.isoformat(),
            })
            results.append({
                "service_name": probe["service_name"],
                "healthy": probe["healthy"],
                "status_code": probe["status_code"],
                "response_time_ms": probe["response_time_ms"],
                "checked_at": snap.checked_at,
            })
    return results


async def stop_monitoring() -> None:
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
    _monitor_task = None
