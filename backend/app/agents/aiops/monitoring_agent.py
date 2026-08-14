"""
Monitoring Agent
=================
Watches incoming service metrics (fed by the synthetic data generator in a
real run, or a real metrics pipeline in production) and flags anomalies
using simple, fast, rule-based thresholds. This agent deliberately does NOT
use the LLM — anomaly detection on numeric thresholds should be instant and
100% deterministic, not dependent on an API call.

Thresholds are loaded from environment-backed settings (config.py), not
hardcoded here, so ops teams can tune them per environment.
"""
from app.core.config import settings


class MonitoringAgent:

    @classmethod
    def detect_anomaly(cls, metrics: dict) -> dict | None:
        """
        metrics example:
        {
            "service_name": "<service from payload>",
            "response_time_ms": 8000,
            "error_rate_pct": 62,
            "db_pool_usage_pct": 95,
            "affected_users_pct": 80,
        }
        Returns an anomaly dict if any threshold is breached, else None.
        """
        reasons = []
        if metrics.get("response_time_ms", 0) > settings.MONITORING_RESPONSE_TIME_MS_THRESHOLD:
            reasons.append("high_response_time")
        if metrics.get("error_rate_pct", 0) > settings.MONITORING_ERROR_RATE_PCT_THRESHOLD:
            reasons.append("high_error_rate")
        if metrics.get("db_pool_usage_pct", 0) > settings.MONITORING_DB_POOL_USAGE_PCT_THRESHOLD:
            reasons.append("connection_pool")

        if not reasons:
            return None

        return {
            "service_name": metrics.get("service_name", "unknown-service"),
            "error_signature": "_".join(reasons) if reasons else "5xx",
            "error_rate_pct": metrics.get("error_rate_pct", 0),
            "affected_users_pct": metrics.get("affected_users_pct", 0),
            "raw_metrics": metrics,
        }

    @classmethod
    def is_recovered(cls, metrics: dict) -> bool:
        """True only when a live probe is healthy and all anomaly thresholds are clear."""
        if metrics.get("healthy") is False:
            return False
        return cls.detect_anomaly(metrics) is None
