"""Demo DB filter — UI API hides seed data, real GitHub rows remain visible."""
from app.services.demo_filters import (
    is_demo_commit_hash,
    is_demo_developer_name,
    is_visible_notification_recipient,
)


def test_demo_developer_names():
    assert is_demo_developer_name("Priya Sharma")
    assert is_demo_developer_name("Karthik Rao")
    assert not is_demo_developer_name("J-Rakshitha")
    assert not is_demo_developer_name("prem-user")
    assert not is_demo_developer_name("asad-dev")


def test_demo_commit_hashes():
    assert is_demo_commit_hash("27a86c3f")
    assert not is_demo_commit_hash("abc12345")


def test_notification_recipient_filter():
    assert is_visible_notification_recipient("github:J-Rakshitha")
    assert is_visible_notification_recipient("github:asad-dev")
    assert is_visible_notification_recipient("ops:Prem")
    assert is_visible_notification_recipient("ops:Asad")
    assert is_visible_notification_recipient("ops:Rakshitha")
    assert is_visible_notification_recipient("ops:Grafana Alert")
    assert not is_visible_notification_recipient("ops:Backend Engineering Team")
    assert not is_visible_notification_recipient("ops:Incident Response")
    assert not is_visible_notification_recipient("ops:On Call")
    assert not is_visible_notification_recipient("ops:Priya Sharma")
    assert not is_visible_notification_recipient("ops:Arjun Mehta")
    assert not is_visible_notification_recipient("Priya Sharma")
    assert not is_visible_notification_recipient("arjun@infosys.com")
    assert not is_visible_notification_recipient("oncall@infosys.com")
    assert is_visible_notification_recipient("real.user@gmail.com")


def test_real_incident_sources_never_hidden():
    """ingest/webhook/monitoring must show even if linked to leftover seed commits."""
    from types import SimpleNamespace
    from app.services.demo_filters import is_demo_incident
    import asyncio

    async def _check():
        for source in ("ingest", "webhook", "monitoring"):
            incident = SimpleNamespace(
                source=source,
                external_references=None,
                linked_commit_id=999,
            )
            assert await is_demo_incident(None, incident) is False

    asyncio.run(_check())


def test_visible_feed_incidents_keeps_history_and_hides_stale_simulate():
    from datetime import datetime, timedelta, timezone
    from app.services.demo_filters import visible_feed_incidents

    now = datetime.now(timezone.utc)
    rows = [
        {"id": 6, "source": "webhook", "triggered_by": "Grafana Alert", "detected_at": now.isoformat()},
        {"id": 5, "source": "ingest", "triggered_by": "Rakshitha", "detected_at": now.isoformat()},
        {"id": 4, "source": "ingest", "triggered_by": "Rakshitha", "detected_at": (now - timedelta(hours=1)).isoformat()},
        {"id": 3, "source": "ingest", "triggered_by": "Prem", "detected_at": (now - timedelta(hours=20)).isoformat()},
        {"id": 2, "source": "ingest", "triggered_by": "Asad", "detected_at": now.isoformat()},
        {"id": 7, "source": "ingest", "triggered_by": "Asad", "detected_at": (now - timedelta(minutes=10)).isoformat()},
        {"id": 1, "source": "monitoring", "triggered_by": "Monitoring Scheduler", "detected_at": now.isoformat()},
        {"id": 0, "source": "simulate", "triggered_by": "System", "detected_at": now.isoformat()},
    ]
    out = visible_feed_incidents(rows)
    # Both Asad + both Rakshitha kept; stale Prem (#3) + simulate hidden
    assert [r["id"] for r in out] == [6, 5, 4, 2, 7, 1]
    assert all(r["source"] != "simulate" for r in out)


def test_sanitize_escalated_to_hides_generic_teams():
    from app.services.demo_filters import sanitize_escalated_to

    assert sanitize_escalated_to("Backend Engineering Team") is None
    assert sanitize_escalated_to("Incident Response") is None
    assert sanitize_escalated_to("On Call") is None
    assert sanitize_escalated_to("Prem Kumar") == "Prem Kumar"
    assert sanitize_escalated_to(None) is None


def test_demo_commit_hash_matches_prefix():
    assert is_demo_commit_hash("27a86c3f")
    assert is_demo_commit_hash("27a86c3fabc")
    assert not is_demo_commit_hash("41402d2e")
    assert not is_demo_commit_hash("abc12345")


def test_sanitize_external_references_keeps_configured_repo_only():
    from app.services.demo_filters import sanitize_external_references
    from app.agents.aiops.external_lookup_agent import ExternalLookupAgent

    allowed = ExternalLookupAgent.configured_repo() or "J-Rakshitha/dev-collab-test-repo"
    refs = [
        {
            "title": "CRITICAL: Synthetic Chaos Exception",
            "url": "https://github.com/harrykimpel/o11yParty-Buzzer/issues/59",
            "repo": "harrykimpel/o11yParty-Buzzer",
        },
        {
            "title": "Pool saturation on checkout",
            "url": f"https://github.com/{allowed}/issues/12",
            "repo": allowed,
        },
        {
            "title": "Chaos Testing Exception",
            "url": "https://github.com/other/repo/issues/1",
            "repo": "other/repo",
        },
    ]
    out = sanitize_external_references(refs)
    assert len(out) == 1
    assert out[0]["repo"] == allowed
    assert "Chaos" not in out[0]["title"]


def test_commit_matches_service_strict():
    from app.agents.coordinator_agent import CoordinatorAgent

    assert CoordinatorAgent.commit_matches_service("checkout-service", "checkout.py") is True
    assert CoordinatorAgent.commit_matches_service("checkout-service", "src/checkout_handler.py") is True
    assert CoordinatorAgent.commit_matches_service("payment-service", "checkout.py") is False
    assert CoordinatorAgent.commit_matches_service("payment-service", "App.jsx") is False
    assert CoordinatorAgent.commit_matches_service("auth-service", "auth_routes.py") is True
    assert CoordinatorAgent.commit_matches_service(None, "checkout.py") is False


def test_sanitize_root_cause_strips_demo_names():
    from app.services.demo_filters import sanitize_root_cause_for_ui

    text = sanitize_root_cause_for_ui(
        "Pool exhaustion after commit 27a86c3f by Arjun Mehta & Karthik Rao in checkout.py"
    )
    assert "27a86c3f" not in text
    assert "Arjun Mehta" not in text
    assert "Karthik Rao" not in text
    assert "[prior change]" not in text
    assert "checkout.py" not in text
    assert "a recent contributor" in text
    assert "service codebase" in text


def test_fallback_root_cause_follows_highest_metric():
    from app.agents.llm.fallback_rules import fallback_root_cause

    pool = fallback_root_cause(
        "checkout-service",
        "high_response_time_high_error_rate_connection_pool",
        raw_metrics={"error_rate_pct": 41, "db_pool_usage_pct": 97, "response_time_ms": 2200},
        triggered_by="Prem",
    )
    assert "Prem" in pool
    assert "connection pool" in pool.lower()
    assert "97" in pool

    err = fallback_root_cause(
        "checkout-service",
        "high_response_time_high_error_rate_connection_pool",
        raw_metrics={"error_rate_pct": 94, "db_pool_usage_pct": 61, "response_time_ms": 2100},
        triggered_by="Rakshitha",
    )
    assert "Rakshitha" in err
    assert "error rate" in err.lower()
    assert "94" in err

    lat = fallback_root_cause(
        "checkout-service",
        "high_response_time_high_error_rate",
        raw_metrics={"error_rate_pct": 42, "db_pool_usage_pct": 62, "response_time_ms": 9800},
        triggered_by="Asad",
    )
    assert "Asad" in lat
    assert "latency" in lat.lower()
    assert "9800" in lat
    assert pool != err != lat


def test_monitoring_is_recovered_requires_live_probe_under_thresholds():
    from app.agents.aiops.monitoring_agent import MonitoringAgent

    assert MonitoringAgent.is_recovered({
        "healthy": True,
        "response_time_ms": 120,
        "error_rate_pct": 1,
        "db_pool_usage_pct": 20,
        "affected_users_pct": 0,
        "service_name": "checkout-service",
    }) is True
    assert MonitoringAgent.is_recovered({
        "healthy": False,
        "response_time_ms": 80,
        "error_rate_pct": 0,
        "db_pool_usage_pct": 10,
        "service_name": "checkout-service",
    }) is False
    assert MonitoringAgent.is_recovered({
        "healthy": True,
        "response_time_ms": 9000,
        "error_rate_pct": 80,
        "db_pool_usage_pct": 97,
        "service_name": "checkout-service",
    }) is False
