import hashlib
import hmac
import json


async def test_incident_includes_sla_fields(client):
    # Real ingest path (simulate is intentionally hidden from the live feed)
    resp = await client.post(
        "/api/incidents/ingest-metrics",
        json={
            "service_name": "payment-service",
            "response_time_ms": 9000,
            "error_rate_pct": 80,
            "db_pool_usage_pct": 95,
            "affected_users_pct": 85,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["anomaly_detected"] is True

    incidents = (await client.get("/api/incidents/")).json()
    assert len(incidents) >= 1
    inc = incidents[0]
    assert inc["sla_minutes"] is not None
    assert inc["sla_deadline"] is not None
    # Status may be escalated; generic "Backend Engineering Team" is sanitized away from UI
    if inc["status"] == "escalated":
        assert inc.get("escalated_to") in (None, "") or "engineering team" not in str(inc.get("escalated_to") or "").lower()


async def test_github_status_includes_webhook_info(client):
    resp = await client.get("/api/dev-collab/github/status")
    body = resp.json()
    assert "webhook_url" in body
    assert body["webhook_url"].endswith("/api/dev-collab/github/webhook")
    assert "webhook_secret_configured" in body


async def test_github_webhook_ping(client, monkeypatch):
    from app.core.config import settings

    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret)
    payload = json.dumps({"zen": "Keep it logically awesome."}).encode()
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    resp = await client.post(
        "/api/dev-collab/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["processed"] is True
    assert resp.json()["action"] == "ping"


async def test_github_webhook_rejects_bad_signature_in_production(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "test-secret")

    payload = b'{"action":"opened","pull_request":{"number":1}}'
    resp = await client.post(
        "/api/dev-collab/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )
    assert resp.status_code == 401


async def test_github_webhook_pull_request_triggers_sync(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "fake-token-for-test")
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret)

    async def _fake_sync(db, trigger="manual"):
        return {"synced": True, "conflicts_found": 0, "trigger": trigger}

    monkeypatch.setattr(
        "app.services.github_webhook_service.run_github_sync",
        _fake_sync,
    )

    payload = json.dumps({"action": "opened", "pull_request": {"number": 42}}).encode()
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    resp = await client.post(
        "/api/dev-collab/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] is True
    assert body["trigger"] == "webhook"
    assert body["pull_request_number"] == 42


async def test_slack_notification_when_configured(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test/webhook")
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "")

    sent = []

    def _fake_send(url, payload, label):
        sent.append({"url": url, "payload": payload, "label": label})
        return True

    monkeypatch.setattr(
        "app.agents.notification_agent.NotificationAgent._send_webhook_sync",
        staticmethod(_fake_send),
    )

    await client.post("/api/dev-collab/simulate-demo-conflict")

    notifications = (await client.get("/api/system/notifications")).json()
    channels = {n["channel"] for n in notifications}
    assert "slack" in channels
    slack_sent = [s for s in sent if s["label"] == "Slack"]
    assert len(slack_sent) == 1
    assert "Conflict" in slack_sent[0]["payload"]["text"]


async def test_discord_notification_when_configured(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(
        settings,
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123456789/test-token",
    )

    sent = []

    def _fake_send(url, payload, label):
        sent.append({"url": url, "payload": payload, "label": label})
        return True

    monkeypatch.setattr(
        "app.agents.notification_agent.NotificationAgent._send_webhook_sync",
        staticmethod(_fake_send),
    )

    await client.post("/api/dev-collab/simulate-demo-conflict")

    notifications = (await client.get("/api/system/notifications")).json()
    channels = {n["channel"] for n in notifications}
    assert "discord" in channels
    labels = {item["label"] for item in sent}
    assert "Discord" in labels


async def test_teams_notification_when_configured(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(
        settings,
        "TEAMS_WEBHOOK_URL",
        "https://outlook.office.com/webhook/test/IncomingWebhook/abc",
    )

    sent = []

    def _fake_send(url, payload, label):
        sent.append({"url": url, "payload": payload, "label": label})
        return True

    monkeypatch.setattr(
        "app.agents.notification_agent.NotificationAgent._send_webhook_sync",
        staticmethod(_fake_send),
    )

    await client.post("/api/incidents/simulate")

    notifications = (await client.get("/api/system/notifications")).json()
    channels = {n["channel"] for n in notifications}
    assert "teams" in channels
    assert sent
    labels = {item["label"] for item in sent}
    assert "Teams" in labels


async def test_integrations_status(client):
    resp = await client.get("/api/system/integrations")
    assert resp.status_code == 200
    body = resp.json()
    assert "slack" in body
    assert "discord" in body
    assert "teams" in body
    assert "email" in body
    assert "github" in body
    assert "configured" in body["teams"]
    assert "team_recipients" in body["email"]


async def test_gmail_email_notification_when_configured(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "NOTIFICATION_SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(settings, "NOTIFICATION_SMTP_USER", "test@gmail.com")
    monkeypatch.setattr(settings, "NOTIFICATION_SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(settings, "NOTIFICATION_TEAM_EMAILS", "demo@gmail.com")
    monkeypatch.setattr(settings, "NOTIFICATION_ONCALL_EMAIL", "demo@gmail.com")

    sent = []

    def _fake_send(recipient, subject, message):
        sent.append({"recipient": recipient, "subject": subject, "message": message})
        return True

    monkeypatch.setattr(
        "app.agents.notification_agent.NotificationAgent._send_email_sync",
        staticmethod(_fake_send),
    )

    await client.post("/api/dev-collab/simulate-demo-conflict")

    notifications = (await client.get("/api/system/notifications")).json()
    email_notes = [n for n in notifications if n["channel"] == "email"]
    assert email_notes
    assert email_notes[0]["recipient"] == "demo@gmail.com"
    assert sent
    assert sent[0]["recipient"] == "demo@gmail.com"


async def test_test_discord_webhook_endpoint_requires_url(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "")
    resp = await client.post("/api/system/test-discord-webhook", json={})
    assert resp.status_code == 400


async def test_test_email_endpoint_requires_smtp(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "NOTIFICATION_SMTP_PASSWORD", "")
    resp = await client.post("/api/system/test-email")
    assert resp.status_code == 400


async def test_teams_webhook_test_endpoint_requires_url(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "")
    resp = await client.post("/api/system/test-teams-webhook", json={})
    assert resp.status_code == 400


def test_github_webhook_signature_verification(monkeypatch):
    from app.services.github_webhook_service import GitHubWebhookService
    from app.core.config import settings

    secret = "my-webhook-secret"
    body = b'{"test": true}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(settings, "ENV", "production")
    assert GitHubWebhookService.verify_signature(body, sig) is True
    assert GitHubWebhookService.verify_signature(body, "sha256=bad") is False
