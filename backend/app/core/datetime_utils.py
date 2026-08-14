"""UTC datetime helpers for API responses."""
from datetime import datetime, timezone


def utc_iso(value: datetime | None) -> str | None:
    """Serialize DB naive-UTC datetimes as ISO-8601 with Z for correct local display."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    iso = value.isoformat()
    return iso if iso.endswith("Z") else f"{iso}Z"


def parse_github_time(value: str | None) -> datetime | None:
    """Parse GitHub API timestamps (e.g. 2026-08-12T17:30:00Z) to naive UTC."""
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None
