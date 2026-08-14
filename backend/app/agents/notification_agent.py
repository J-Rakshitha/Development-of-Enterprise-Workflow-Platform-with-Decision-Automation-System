"""
Notification Agent
==================
Delivers team alerts when agents complete significant actions. Channels:
  - WebSocket — live dashboard updates (always)
  - Email — real SMTP when configured, otherwise simulated delivery logged to DB
  - Slack — incoming webhook when SLACK_WEBHOOK_URL is configured
  - Discord — incoming webhook when DISCORD_WEBHOOK_URL is configured
  - Microsoft Teams — incoming webhook when TEAMS_WEBHOOK_URL is configured

Every delivery is persisted in TeamNotification so the audit trail survives
page refreshes and can be queried via REST.
"""
import logging
import smtplib
from email.mime.text import MIMEText

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.models.notification import TeamNotification
from app.agents.coordinator_agent import CoordinatorAgent
from app.routers.websocket_routes import manager

logger = logging.getLogger("notification_agent")

DEFAULT_TEAM_RECIPIENTS: list[str] = []


def _smtp_configured() -> bool:
    return bool((settings.NOTIFICATION_SMTP_HOST or "").strip())


class NotificationAgent:

    @staticmethod
    def team_email_recipients() -> list[str]:
        """Real inboxes from .env when configured; otherwise demo addresses for simulated email."""
        custom = (settings.NOTIFICATION_TEAM_EMAILS or "").strip()
        if custom:
            return [e.strip() for e in custom.split(",") if e.strip()]
        if _smtp_configured():
            oncall = (settings.NOTIFICATION_ONCALL_EMAIL or "").strip()
            if oncall:
                return [oncall]
        return list(DEFAULT_TEAM_RECIPIENTS)

    @staticmethod
    def smtp_ready() -> bool:
        return (
            settings.NOTIFICATION_EMAIL_ENABLED
            and _smtp_configured()
            and bool((settings.NOTIFICATION_SMTP_USER or "").strip())
            and bool((settings.NOTIFICATION_SMTP_PASSWORD or "").strip())
        )

    @staticmethod
    def send_email(subject: str, message: str, recipient: str | None = None) -> bool:
        to_addr = recipient or (settings.NOTIFICATION_ONCALL_EMAIL or "").strip()
        if not to_addr:
            return False
        return NotificationAgent._send_email_sync(to_addr, subject, message)

    @staticmethod
    async def list_recent(db, limit: int = 30) -> list[TeamNotification]:
        stmt = select(TeamNotification).order_by(TeamNotification.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def _persist(
        db,
        channel: str,
        event_type: str,
        module: str,
        recipient: str,
        subject: str,
        message: str,
        related_entity_id: int | None = None,
        delivered: bool = True,
    ) -> TeamNotification:
        entry = TeamNotification(
            channel=channel,
            event_type=event_type,
            module=module,
            recipient=recipient,
            subject=subject,
            message=message,
            related_entity_id=related_entity_id,
            delivered=delivered,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry

    @staticmethod
    def _send_email_sync(recipient: str, subject: str, message: str) -> bool:
        if not settings.NOTIFICATION_SMTP_HOST:
            return False
        try:
            msg = MIMEText(message)
            msg["Subject"] = subject
            msg["From"] = settings.NOTIFICATION_FROM_EMAIL
            msg["To"] = recipient
            with smtplib.SMTP(settings.NOTIFICATION_SMTP_HOST, settings.NOTIFICATION_SMTP_PORT, timeout=12) as server:
                if settings.NOTIFICATION_SMTP_USER:
                    server.starttls()
                    server.login(settings.NOTIFICATION_SMTP_USER, settings.NOTIFICATION_SMTP_PASSWORD)
                server.send_message(msg)
            return True
        except Exception as exc:
            logger.warning("Email delivery failed for %s: %s", recipient, exc)
            return False

    @staticmethod
    def _send_webhook_sync(url: str, payload: dict, label: str) -> bool:
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("%s webhook delivery failed: %s", label, exc)
            return False

    @staticmethod
    def _teams_payloads(subject: str, message: str, url: str) -> list[dict]:
        """Office 365 connectors use MessageCard; Power Automate webhooks often expect plain text."""
        text = f"{subject}\n\n{message}"
        payloads = [{"text": text}]
        if "logic.azure.com" not in url and "powerautomate" not in url.lower():
            payloads.append({
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "summary": subject,
                "themeColor": "0076D7",
                "title": subject,
                "text": message.replace("\n", "<br>"),
            })
        else:
            payloads.append({
                "title": subject,
                "text": message,
            })
        return payloads

    @staticmethod
    def send_teams_webhook(url: str, subject: str, message: str) -> bool:
        """Post to Teams — tries compatible payload shapes until one succeeds."""
        url = (url or "").strip()
        if not url:
            return False
        for payload in NotificationAgent._teams_payloads(subject, message, url):
            if NotificationAgent._send_webhook_sync(url, payload, "Teams"):
                return True
        return False

    @staticmethod
    def send_discord_webhook(url: str, subject: str, message: str) -> bool:
        """Post to Discord channel webhook — tries embed then plain content."""
        url = (url or "").strip()
        if not url:
            return False
        text = f"**{subject}**\n{message}"
        if len(text) > 2000:
            text = text[:1997] + "..."
        payloads = [
            {
                "embeds": [{
                    "title": subject[:256],
                    "description": message[:4096],
                    "color": 5814783,
                }],
            },
            {"content": text},
        ]
        for payload in payloads:
            if NotificationAgent._send_webhook_sync(url, payload, "Discord"):
                return True
        return False

    @staticmethod
    async def _deliver_discord(db, subject: str, message: str, event_type: str,
                               module: str, related_entity_id: int | None) -> TeamNotification | None:
        url = (settings.DISCORD_WEBHOOK_URL or "").strip()
        if not url:
            return None
        delivered = NotificationAgent.send_discord_webhook(url, subject, message)
        channel = "discord" if delivered else "discord_failed"
        return await NotificationAgent._persist(
            db, channel, event_type, module, "discord-channel", subject, message,
            related_entity_id, delivered,
        )

    @staticmethod
    async def _deliver_slack(db, subject: str, message: str, event_type: str,
                              module: str, related_entity_id: int | None) -> TeamNotification | None:
        url = (settings.SLACK_WEBHOOK_URL or "").strip()
        if not url:
            return None
        text = f"*{subject}*\n{message}"
        delivered = NotificationAgent._send_webhook_sync(url, {"text": text}, "Slack")
        channel = "slack" if delivered else "slack_failed"
        return await NotificationAgent._persist(
            db, channel, event_type, module, "slack-channel", subject, message,
            related_entity_id, delivered,
        )

    @staticmethod
    async def _deliver_teams(db, subject: str, message: str, event_type: str,
                              module: str, related_entity_id: int | None) -> TeamNotification | None:
        url = (settings.TEAMS_WEBHOOK_URL or "").strip()
        if not url:
            return None
        delivered = NotificationAgent.send_teams_webhook(url, subject, message)
        channel = "teams" if delivered else "teams_failed"
        return await NotificationAgent._persist(
            db, channel, event_type, module, "teams-channel", subject, message,
            related_entity_id, delivered,
        )

    @staticmethod
    async def _deliver_email(db, recipient: str, subject: str, message: str, event_type: str,
                              module: str, related_entity_id: int | None) -> TeamNotification:
        if NotificationAgent.smtp_ready():
            delivered = NotificationAgent._send_email_sync(recipient, subject, message)
            channel = "email" if delivered else "email_failed"
        elif settings.NOTIFICATION_EMAIL_ENABLED and _smtp_configured():
            delivered = False
            channel = "email_failed"
        else:
            delivered = True
            channel = "email_simulated"

        return await NotificationAgent._persist(
            db, channel, event_type, module, recipient, subject, message, related_entity_id, delivered
        )

    @staticmethod
    async def _notify_team(
        db,
        event_type: str,
        module: str,
        subject: str,
        message: str,
        related_entity_id: int | None = None,
        ws_payload: dict | None = None,
        recipients: list[str] | None = None,
    ) -> list[TeamNotification]:
        targets = recipients if recipients is not None else NotificationAgent.team_email_recipients()
        sent: list[TeamNotification] = []

        for recipient in targets:
            sent.append(await NotificationAgent._deliver_email(
                db, recipient, subject, message, event_type, module, related_entity_id
            ))

        slack_entry = await NotificationAgent._deliver_slack(
            db, subject, message, event_type, module, related_entity_id
        )
        if slack_entry:
            sent.append(slack_entry)

        discord_entry = await NotificationAgent._deliver_discord(
            db, subject, message, event_type, module, related_entity_id
        )
        if discord_entry:
            sent.append(discord_entry)

        teams_entry = await NotificationAgent._deliver_teams(
            db, subject, message, event_type, module, related_entity_id
        )
        if teams_entry:
            sent.append(teams_entry)

        await NotificationAgent._persist(
            db, "websocket", event_type, module, "dashboard", subject, message, related_entity_id
        )

        if ws_payload is not None:
            await manager.broadcast("team_notification", ws_payload)

        await CoordinatorAgent.log_decision(
            db=db,
            agent_name="Notification Agent",
            module=module,
            decision_summary=f"Notified team ({event_type}): {subject}",
            used_llm=False,
            related_entity_id=related_entity_id,
        )

        return sent

    @staticmethod
    async def notify_conflict_detected(
        db,
        conflict_id: int,
        file_path: str,
        function_name: str | None,
        dev_a: str,
        dev_b: str,
        risk_score: float,
        code_review: str | None = None,
        recipients: list[str] | None = None,
    ) -> list[TeamNotification]:
        fn = function_name or "(file-level)"
        subject = f"[Dev-Collab] Conflict risk {risk_score}% — {file_path}"
        message = (
            f"Merge conflict predicted between {dev_a} and {dev_b} "
            f"in {file_path} ({fn}). Risk score: {risk_score}%."
        )
        if code_review:
            message += f"\n\nCode review:\n{code_review}"

        return await NotificationAgent._notify_team(
            db,
            event_type="conflict_detected",
            module="dev_collab",
            subject=subject,
            message=message,
            related_entity_id=conflict_id,
            recipients=recipients,
            ws_payload={
                "event_type": "conflict_detected",
                "conflict_id": conflict_id,
                "file_path": file_path,
                "function_name": function_name,
                "dev_a": dev_a,
                "dev_b": dev_b,
                "risk_score": risk_score,
                "subject": subject,
            },
        )

    @staticmethod
    async def notify_conflict_resolved(
        db,
        conflict_id: int,
        file_path: str,
        suggestion: str,
        dev_a: str,
        dev_b: str,
    ) -> list[TeamNotification]:
        subject = f"[Dev-Collab] Conflict resolved — {file_path}"
        message = (
            f"Conflict between {dev_a} and {dev_b} in {file_path} was resolved.\n"
            f"AI suggestion: {suggestion}"
        )
        return await NotificationAgent._notify_team(
            db,
            event_type="conflict_resolved",
            module="dev_collab",
            subject=subject,
            message=message,
            related_entity_id=conflict_id,
            ws_payload={
                "event_type": "conflict_resolved",
                "conflict_id": conflict_id,
                "file_path": file_path,
                "subject": subject,
            },
        )

    @staticmethod
    async def notify_incident_created(
        db,
        incident_id: int,
        service_name: str,
        severity: str,
        root_cause: str,
        status: str,
        sla_deadline: str | None = None,
        escalated_to: str | None = None,
        triggered_by: str | None = None,
    ) -> list[TeamNotification]:
        subject = f"[AIOps] {severity} incident on {service_name}"
        message = (
            f"Incident #{incident_id} on {service_name} — severity {severity}, status {status}.\n"
            f"Root cause: {root_cause}"
        )
        if sla_deadline:
            message += f"\nSLA deadline: {sla_deadline}"
        if escalated_to:
            message += f"\nEscalated to: {escalated_to}"
        if triggered_by:
            message += f"\nTriggered by: {triggered_by}"

        # Dashboard shows the person who triggered (Prem / Grafana), not escalation team
        who = (triggered_by or "").strip()
        if not who or who.lower() in (
            "on-call", "on call", "oncall",
            "backend engineering team", "incident response", "sla watchdog",
        ):
            # No person label → skip ops:* card (still email on-call if configured)
            recipients = []
        else:
            recipients = [f"ops:{who}"]

        # Also deliver to real on-call inbox when configured (non-demo)
        oncall = (settings.NOTIFICATION_ONCALL_EMAIL or "").strip()
        if oncall and not oncall.endswith("@infosys.com") and oncall not in recipients:
            recipients.append(oncall)
        team = (settings.NOTIFICATION_TEAM_EMAILS or "").strip()
        if team:
            for email in [e.strip() for e in team.split(",") if e.strip()]:
                if email.endswith("@infosys.com"):
                    continue
                if email not in recipients:
                    recipients.append(email)

        return await NotificationAgent._notify_team(
            db,
            event_type="incident_created",
            module="aiops",
            subject=subject,
            message=message,
            related_entity_id=incident_id,
            recipients=recipients,
            ws_payload={
                "event_type": "incident_created",
                "incident_id": incident_id,
                "service_name": service_name,
                "severity": severity,
                "subject": subject,
                "triggered_by": who,
            },
        )
