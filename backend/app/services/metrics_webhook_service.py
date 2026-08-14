"""
Observability alert webhook — enterprise AIOps (Grafana/Prometheus pattern).

Mirrors GitHub webhook integration for Dev-Collab: external systems push
real metrics; no JWT required — verified via shared secret header.
"""
import json
import logging
import random

from app.core.config import settings

logger = logging.getLogger("metrics_webhook")


def _label_float(labels: dict, key: str, default_lo: float, default_hi: float) -> float:
    if key in labels and labels[key] is not None and labels[key] != "":
        try:
            return float(labels[key])
        except (TypeError, ValueError):
            pass
    return round(random.uniform(default_lo, default_hi), 1)


def _label_int(labels: dict, key: str, default_lo: int, default_hi: int) -> int:
    if key in labels and labels[key] is not None and labels[key] != "":
        try:
            return int(float(labels[key]))
        except (TypeError, ValueError):
            pass
    return random.randint(default_lo, default_hi)


class MetricsWebhookService:

    @staticmethod
    def webhook_url() -> str:
        base = settings.PUBLIC_BACKEND_URL.rstrip("/")
        return f"{base}/api/incidents/alert-webhook"

    @staticmethod
    def verify_secret(secret_header: str | None) -> bool:
        expected = (settings.METRICS_WEBHOOK_SECRET or "").strip()
        if not expected:
            if settings.ENV == "development":
                logger.warning("METRICS_WEBHOOK_SECRET not set — accepting webhook in development mode")
                return True
            logger.error("METRICS_WEBHOOK_SECRET required in non-development environments")
            return False
        if not secret_header:
            logger.warning("Metrics webhook rejected: missing X-Metrics-Webhook-Secret header")
            return False
        return secret_header.strip() == expected

    @staticmethod
    def secret_header_from_request(request) -> str | None:
        return (
            request.headers.get("x-metrics-webhook-secret")
            or request.headers.get("X-Metrics-Webhook-Secret")
            or request.headers.get("X-METRICS-WEBHOOK-SECRET")
        )

    @staticmethod
    def parse_payload(payload_body: bytes) -> dict:
        return json.loads(payload_body.decode("utf-8"))

    @staticmethod
    def normalize_metrics(payload: dict) -> dict | None:
        """Map direct metrics JSON or common Grafana alert payloads to pipeline input."""
        if not isinstance(payload, dict):
            return None

        # Direct fields or common camelCase aliases from Postman/APIs
        service = (
            payload.get("service_name")
            or payload.get("serviceName")
            or payload.get("service")
        )
        if service:
            return {
                "service_name": str(service),
                "response_time_ms": int(
                    payload.get("response_time_ms")
                    or payload.get("responseTimeMs")
                    or 0
                ),
                "error_rate_pct": float(
                    payload.get("error_rate_pct")
                    or payload.get("errorRatePct")
                    or 0
                ),
                "db_pool_usage_pct": float(
                    payload.get("db_pool_usage_pct")
                    or payload.get("dbPoolUsagePct")
                    or 0
                ),
                "affected_users_pct": float(
                    payload.get("affected_users_pct")
                    or payload.get("affectedUsersPct")
                    or 0
                ),
            }

        alerts = payload.get("alerts")
        if isinstance(alerts, list) and alerts:
            alert = alerts[0] if isinstance(alerts[0], dict) else {}
            labels = alert.get("labels") or {}
            annotations = alert.get("annotations") or {}
            service = (
                labels.get("service_name")
                or labels.get("service")
                or labels.get("job")
                or annotations.get("service")
                or "observed-service"
            )
            summary = annotations.get("summary") or annotations.get("description") or ""
            # Prefer label values; only synthesize within realistic ranges when labels omit metrics
            error_rate = _label_float(labels, "error_rate_pct", 45.0, 90.0)
            if "high" in summary.lower() or alert.get("status") == "firing":
                error_rate = max(error_rate, 60.0)
            return {
                "service_name": str(service),
                "response_time_ms": _label_int(labels, "response_time_ms", 2500, 9000),
                "error_rate_pct": error_rate,
                "db_pool_usage_pct": _label_float(labels, "db_pool_usage_pct", 55.0, 95.0),
                "affected_users_pct": _label_float(labels, "affected_users_pct", 40.0, 90.0),
            }

        common_labels = payload.get("commonLabels") or {}
        if common_labels:
            service = (
                common_labels.get("service_name")
                or common_labels.get("service")
                or "observed-service"
            )
            return {
                "service_name": str(service),
                "response_time_ms": _label_int(common_labels, "response_time_ms", 2500, 9000),
                "error_rate_pct": _label_float(common_labels, "error_rate_pct", 45.0, 90.0),
                "db_pool_usage_pct": _label_float(common_labels, "db_pool_usage_pct", 55.0, 95.0),
                "affected_users_pct": _label_float(common_labels, "affected_users_pct", 40.0, 90.0),
            }

        return None
