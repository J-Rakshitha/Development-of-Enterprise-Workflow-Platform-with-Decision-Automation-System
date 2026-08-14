"""
Filter seed / simulated demo rows from UI-facing API responses.

Real GitHub data (source=github, github:* recipients, real GitHub usernames)
remains visible. Rows from seed_full_demo.py and simulate flows stay in DB
but are hidden from dashboard endpoints.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dev_collab.code_watch_agent import DEMO_DEV_NAMES
from app.models.dev_collab import CommitLog, ConflictEvent, Developer
from app.models.incident import Incident
from app.models.notification import TeamNotification

DEMO_COMMIT_HASHES = frozenset({"27a86c3f", "b14e352e"})
DEMO_SEED_EXTERNAL_REF_MARKERS = (
    "github.com/issues/101",
    "Synthetic Chaos Exception",
    "Chaos Testing Exception",
    "o11yParty",
    "o11yParty-Buzzer",
)


def is_demo_developer_name(name: str | None) -> bool:
    return (name or "") in DEMO_DEV_NAMES


def is_demo_commit_hash(commit_hash: str | None) -> bool:
    h = (commit_hash or "").strip().lower()
    if not h:
        return False
    if h in DEMO_COMMIT_HASHES:
        return True
    # Short UI hashes still match known seed prefixes
    return any(h.startswith(demo) or demo.startswith(h) for demo in DEMO_COMMIT_HASHES if len(h) >= 7)


# Escalation team names — not a signed-in person; hide from Team Notifications
_HIDDEN_OPS_LABELS = frozenset({
    "backend engineering team",
    "incident response",
    "sla watchdog",
    "on call",
    "on-call",
    "oncall",
})


def is_visible_notification_recipient(recipient: str | None) -> bool:
    r = (recipient or "").strip()
    if not r:
        return False
    # Hide leftover seed demo inboxes only
    if r.endswith("@infosys.com"):
        return False
    # Enterprise real-time labels (GitHub PR authors / AIOps person who triggered)
    if r.startswith("github:"):
        label = r[7:].strip()
        if is_demo_developer_name(label):
            return False
        return True
    if r.startswith("ops:"):
        label = r[4:].strip()
        if label.lower() in _HIDDEN_OPS_LABELS:
            return False
        # Seed demo developers (Priya Sharma, Arjun Mehta, …) — not real JWT users
        if is_demo_developer_name(label):
            return False
        return True
    if is_demo_developer_name(r):
        return False
    return True


def is_demo_incident_external_refs(external_references: str | None) -> bool:
    if not external_references:
        return False
    return any(marker in external_references for marker in DEMO_SEED_EXTERNAL_REF_MARKERS)


def sanitize_external_references(refs) -> list:
    """
    AIOps UI: only keep GitHub refs from the configured enterprise repo.
    Drops public chaos/demo search hits already stored on older incidents.
    """
    if not refs:
        return []
    if isinstance(refs, str):
        import json

        try:
            refs = json.loads(refs)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(refs, list):
        return []

    from app.agents.aiops.external_lookup_agent import ExternalLookupAgent

    allowed = ExternalLookupAgent.configured_repo()
    return [
        ref for ref in refs
        if isinstance(ref, dict) and ExternalLookupAgent.is_allowed_ref(ref, allowed)
    ]


async def is_demo_commit(db: AsyncSession, commit: CommitLog) -> bool:
    if is_demo_commit_hash(commit.commit_hash):
        return True
    # Seed messages often embed demo developer names even if hash check misses
    msg = commit.message or ""
    if any(name in msg for name in DEMO_DEV_NAMES):
        return True
    dev = await db.get(Developer, commit.developer_id)
    return is_demo_developer_name(dev.name if dev else None)


def sanitize_root_cause_for_ui(root_cause: str | None) -> str | None:
    """Strip leftover seed commit / demo-name mentions from displayed root cause."""
    if not root_cause:
        return root_cause
    import re

    had_demo_hash = any(h in root_cause for h in DEMO_COMMIT_HASHES)
    text = root_cause
    for hash_ in DEMO_COMMIT_HASHES:
        text = text.replace(hash_, "[prior change]")
    for name in DEMO_DEV_NAMES:
        text = text.replace(name, "a recent contributor")
    # Remove seed-link phrasing that made Prem/Rakshitha incidents look identical
    text = re.sub(r"\s*\(commit\s*\[prior change\]\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*commit\s*\[prior change\]", "", text, flags=re.IGNORECASE)
    if had_demo_hash or "[prior change]" in text:
        text = re.sub(r"`?checkout\.py`?", "the service codebase", text, flags=re.IGNORECASE)
        text = text.replace("[prior change]", "")
    return " ".join(text.split())


async def visible_linked_commit(
    db: AsyncSession,
    commit: CommitLog | None,
    service_name: str | None = None,
) -> dict | None:
    """
    Return linked commit for UI only when it is not seed/demo data AND
    (if service_name given) the commit file actually matches that service.
    Hides weak historical links (e.g. payment-service → unrelated PR merge).
    """
    if not commit or await is_demo_commit(db, commit):
        return None
    if service_name:
        from app.agents.coordinator_agent import CoordinatorAgent

        if not CoordinatorAgent.commit_matches_service(service_name, commit.file_path):
            return None
    return {
        "commit_hash": commit.commit_hash,
        "file_path": commit.file_path,
        "message": commit.message,
        "had_conflict": commit.had_conflict,
    }


async def is_demo_incident(db: AsyncSession, incident: Incident) -> bool:
    # Real enterprise sources always visible — even if Coordinator linked a leftover seed commit
    if (incident.source or "") in ("ingest", "webhook", "monitoring"):
        return False
    if (incident.source or "") == "simulate":
        return True
    if is_demo_incident_external_refs(incident.external_references):
        return True
    if incident.linked_commit_id:
        commit = await db.get(CommitLog, incident.linked_commit_id)
        if commit and await is_demo_commit(db, commit):
            return True
    return False


async def count_visible_conflicts(db: AsyncSession) -> int:
    return await db.scalar(
        select(func.count()).select_from(ConflictEvent).where(ConflictEvent.source == "github")
    ) or 0


async def count_visible_open_incidents(db: AsyncSession) -> int:
    result = await db.execute(
        select(Incident).where(Incident.status.in_(["open", "escalated"]))
    )
    visible = 0
    for incident in result.scalars().all():
        if not await is_demo_incident(db, incident):
            visible += 1
    return visible


async def count_visible_linked_incidents(db: AsyncSession) -> int:
    result = await db.execute(
        select(Incident).where(Incident.linked_commit_id.isnot(None))
    )
    visible = 0
    for incident in result.scalars().all():
        if not await is_demo_incident(db, incident):
            visible += 1
    return visible


def is_human_triggered_by(name: str | None) -> bool:
    """True for any signed-in person; false for Grafana/system labels."""
    n = (name or "").strip().lower()
    if not n:
        return False
    return n not in {
        "system",
        "api",
        "simulate",
        "grafana alert",
        "monitoring scheduler",
        "sla watchdog",
        "incident response",
        "backend engineering team",
        "on call",
        "on-call",
        "oncall",
    }


LIVE_FEED_MAX_AGE_HOURS = 6


def sanitize_escalated_to(value: str | None) -> str | None:
    """Hide generic / fake-demo escalation team labels from UI (status stays escalated)."""
    if not value:
        return None
    label = value.strip().lower()
    if label in _HIDDEN_OPS_LABELS:
        return None
    return value.strip()


def _parse_detected_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def visible_feed_incidents(rows: list[dict], limit: int = 50) -> list[dict]:
    """
    Live Incident Feed: recent real AIOps sources (ingest / webhook / monitoring).
    Simulate stays hidden. Stale rows (>6h) stay in DB but are hidden.
    Each trigger keeps its own card (history) — no per-person overwrite in the UI.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LIVE_FEED_MAX_AGE_HOURS)
    out: list[dict] = []
    for row in rows:
        source = (row.get("source") or "").strip().lower()
        if source == "simulate":
            continue

        detected = _parse_detected_at(row.get("detected_at"))
        if detected is not None and detected < cutoff:
            continue

        # Enterprise observability sources — eligible (UI badges: INGEST/WEBHOOK/MONITORING)
        if source in ("ingest", "webhook", "monitoring"):
            out.append(row)
            continue

        # Legacy / unknown source: only signed-in human triggers
        if not is_human_triggered_by(row.get("triggered_by")):
            continue
        out.append(row)
    return out[:limit]


# Back-compat alias used by older imports/tests
def latest_incident_per_triggered_by(rows: list[dict]) -> list[dict]:
    return visible_feed_incidents(rows)
