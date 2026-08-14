"""
External Lookup Agent — Tool & System Integration
=====================================================
Looks up related issues in the configured enterprise GitHub repo only
(GITHUB_REPO_OWNER / GITHUB_REPO_NAME). Public internet hits (chaos demos,
unrelated repos) are discarded so AIOps cards stay company-relevant.

Network calls are wrapped in a strict timeout + try/except so a
slow/unreachable external API can NEVER break the incident pipeline —
it just degrades to an empty result.
"""
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger("external_lookup_agent")

GITHUB_SEARCH_URL = "https://api.github.com/search/issues"

# Titles/URLs that look like public chaos demos — never show on enterprise cards
_BLOCKED_REF_MARKERS = (
    "chaos",
    "synthetic chaos",
    "synthetic",
    "o11yparty",
    "o11y-party",
    "buzzer",
)


class ExternalLookupAgent:

    @staticmethod
    def configured_repo() -> str:
        owner = (settings.GITHUB_REPO_OWNER or "").strip()
        name = (settings.GITHUB_REPO_NAME or "").strip()
        if owner and name:
            return f"{owner}/{name}"
        return ""

    @staticmethod
    def is_allowed_ref(ref: dict | None, allowed_repo: str | None = None) -> bool:
        """Keep only refs from the configured repo; drop chaos/demo public noise."""
        if not isinstance(ref, dict):
            return False
        repo_slug = (allowed_repo if allowed_repo is not None else ExternalLookupAgent.configured_repo()).strip()
        if not repo_slug:
            return False

        title = (ref.get("title") or "").lower()
        url = (ref.get("url") or "").lower()
        repo = (ref.get("repo") or "").lower()
        blob = f"{title} {url} {repo}"
        if any(marker in blob for marker in _BLOCKED_REF_MARKERS):
            return False

        slug = repo_slug.lower()
        return slug == repo or f"github.com/{slug}".lower() in url or f"/{slug}/".lower() in url

    @staticmethod
    async def find_related_issues(query: str, timeout: float = 4.0, max_results: int = 3) -> list[dict]:
        """
        Search issues in the configured GitHub repo only. Returns [] when
        repo is unset, API fails, or no clean matches — never blocks the pipeline.
        """
        allowed = ExternalLookupAgent.configured_repo()
        if not allowed:
            logger.info("External lookup skipped — GITHUB_REPO_OWNER/NAME not configured")
            return []

        # Scope search to enterprise repo; still filter results defensively
        q = f"repo:{allowed} {query} in:title".strip()
        params = {"q": q, "per_page": max(max_results * 2, 5)}
        headers = {"Accept": "application/vnd.github+json"}
        token = (settings.GITHUB_TOKEN or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(GITHUB_SEARCH_URL, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning(f"External lookup (GitHub) unavailable, skipping enrichment: {exc}")
            return []

        items = data.get("items", [])
        mapped = [
            {
                "title": item.get("title", ""),
                "url": item.get("html_url", ""),
                "repo": (item.get("repository_url", "").split("/repos/")[-1]) or "unknown/repo",
            }
            for item in items
        ]
        return [ref for ref in mapped if ExternalLookupAgent.is_allowed_ref(ref, allowed)][:max_results]
