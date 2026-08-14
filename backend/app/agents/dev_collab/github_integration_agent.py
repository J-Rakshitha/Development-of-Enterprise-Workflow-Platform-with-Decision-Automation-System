"""
GitHub Integration Agent — Phase A: Real, live data instead of simulation
=============================================================================
Connects to a REAL GitHub repository via the GitHub REST API and detects
ACTUAL merge conflicts — two different ways, both using real data:

  1. "Confirmed conflicts" — GitHub itself computes `mergeable_state` for
     every open Pull Request. When it's 'dirty', GitHub has already found
     a real conflict between that PR and the base branch.

  2. "Predicted conflicts" — even when individual PRs are still mergeable,
     if TWO OR MORE open PRs touch the SAME file, that's a real, live
     early-warning signal — the same idea as the original Conflict
     Prediction Agent, just fed with genuine repo activity instead of a
     simulate-button.

Network/API failures degrade gracefully — a GitHub outage or bad token
must never crash the pipeline, consistent with the rest of this system.
"""
import asyncio
import logging
from collections import defaultdict

import httpx

from app.core.config import settings

logger = logging.getLogger("github_integration_agent")

GITHUB_API_BASE = "https://api.github.com"


class GitHubIntegrationAgent:

    @staticmethod
    def _headers() -> dict:
        headers = {"Accept": "application/vnd.github+json"}
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
        return headers

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.GITHUB_TOKEN and settings.GITHUB_REPO_OWNER and settings.GITHUB_REPO_NAME)

    @staticmethod
    async def fetch_open_pull_requests() -> dict:
        """
        Returns {"connected": bool, "pull_requests": [...], "error": str|None}.
        Each pull request dict: number, title, author, files (list of filenames),
        mergeable_state ('clean' | 'dirty' | 'unknown' | ...).
        """
        if not GitHubIntegrationAgent.is_configured():
            return {"connected": False, "pull_requests": [], "error": "GitHub not configured (missing token/repo in .env)."}

        owner, repo = settings.GITHUB_REPO_OWNER, settings.GITHUB_REPO_NAME
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls"

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=GitHubIntegrationAgent._headers()) as client:
                resp = await client.get(url, params={"state": "open", "per_page": 30})
                if resp.status_code == 404:
                    return {"connected": False, "pull_requests": [], "error": f"Repository {owner}/{repo} not found or token can't access it."}
                if resp.status_code == 401:
                    return {"connected": False, "pull_requests": [], "error": "GitHub token is invalid or expired."}
                resp.raise_for_status()
                prs_raw = resp.json()

                async def fetch_pr_extras(pr):
                    number = pr["number"]
                    detail_task = client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}")
                    files_task = client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/files")
                    detail_resp, files_resp = await asyncio.gather(detail_task, files_task)

                    mergeable_state = "unknown"
                    if detail_resp.status_code == 200:
                        mergeable_state = detail_resp.json().get("mergeable_state") or "unknown"
                    files = [f["filename"] for f in files_resp.json()] if files_resp.status_code == 200 else []

                    return {
                        "number": number,
                        "title": pr["title"],
                        "author": pr["user"]["login"],
                        "branch": pr["head"]["ref"],
                        "files": files,
                        "mergeable_state": mergeable_state,
                        "url": pr["html_url"],
                        # PR raise time (prefer list payload; fall back to detail)
                        "created_at": (
                            pr.get("created_at")
                            or (detail_resp.json().get("created_at") if detail_resp.status_code == 200 else None)
                        ),
                    }

                pull_requests = await asyncio.gather(*(fetch_pr_extras(pr) for pr in prs_raw))
                return {"connected": True, "pull_requests": list(pull_requests), "error": None}

        except httpx.RequestError as exc:
            logger.warning(f"GitHub API unreachable (non-fatal): {type(exc).__name__}: {exc!r}")
            return {"connected": False, "pull_requests": [], "error": f"Could not reach GitHub — {type(exc).__name__}: {exc}"}
        except Exception as exc:
            logger.warning(f"GitHub integration error (non-fatal): {exc}")
            return {"connected": False, "pull_requests": [], "error": str(exc)}

    @staticmethod
    def find_real_conflicts(pull_requests: list[dict]) -> list[dict]:
        """
        Pure logic (no network) — given the live PR data, find:
          - PRs GitHub itself flagged as 'dirty' (confirmed real conflict)
          - Files touched by 2+ open PRs (predicted conflict)
        Returns a list of conflict dicts ready to become ConflictEvent rows.
        """
        conflicts = []

        # 1. Confirmed conflicts (GitHub-reported)
        for pr in pull_requests:
            if pr["mergeable_state"] == "dirty":
                conflicts.append({
                    "type": "confirmed",
                    "file_path": ", ".join(pr["files"][:3]) or "(unknown files)",
                    "function_name": f"PR #{pr['number']}",
                    "dev_a": pr["author"],
                    "dev_b": "base branch",
                    "risk_score": 95.0,
                    "source_url": pr["url"],
                })

        # 2. Predicted conflicts (same file touched by multiple open PRs)
        file_to_prs = defaultdict(list)
        for pr in pull_requests:
            for f in pr["files"]:
                file_to_prs[f].append(pr)

        seen_pairs = set()
        for file_path, prs in file_to_prs.items():
            if len(prs) < 2:
                continue
            for i in range(len(prs)):
                for j in range(i + 1, len(prs)):
                    pr_a, pr_b = prs[i], prs[j]
                    pair_key = tuple(sorted([pr_a["number"], pr_b["number"]])) + (file_path,)
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    conflicts.append({
                        "type": "predicted",
                        "file_path": file_path,
                        "function_name": f"PR #{pr_a['number']} vs #{pr_b['number']}",
                        "dev_a": pr_a["author"],
                        "dev_b": pr_b["author"],
                        "risk_score": 70.0,
                        "source_url": pr_a["url"],
                    })

        return conflicts
