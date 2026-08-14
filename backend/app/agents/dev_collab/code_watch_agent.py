"""
Code-Watch Agent
=================
Records live "presence" — which developer is editing which file/function
right now. In a real IDE integration this would be fed by a VS Code
extension or git pre-commit hook. For this project, it's fed by the
synthetic data generator (Phase 9) and/or a manual "simulate edit" API call.
"""
from datetime import datetime
from sqlalchemy import select

from app.models.dev_collab import FileEditSession, Developer
from app.core.datetime_utils import parse_github_time

DEMO_DEV_NAMES = frozenset({
    "Priya Sharma",
    "Arjun Mehta",
    "Sneha Reddy",
    "Karthik Rao",
})

GITHUB_AVATAR_COLORS = ("#4F8CFF", "#FF6B6B", "#3ECF8E", "#F5A623", "#9B59B6", "#E67E22")


class CodeWatchAgent:

    @staticmethod
    async def get_or_create_developer(db, name: str, avatar_color: str = "#6C63FF") -> Developer:
        stmt = select(Developer).where(Developer.name == name)
        result = await db.execute(stmt)
        dev = result.scalars().first()
        if dev:
            return dev
        dev = Developer(name=name, avatar_color=avatar_color)
        db.add(dev)
        await db.commit()
        await db.refresh(dev)
        return dev

    @staticmethod
    async def start_edit_session(
        db,
        developer_id: int,
        file_path: str,
        function_name: str | None,
        started_at: datetime | None = None,
    ) -> FileEditSession:
        session = FileEditSession(
            developer_id=developer_id,
            file_path=file_path,
            function_name=function_name,
            started_at=started_at or datetime.utcnow(),
            is_active=True,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    async def end_edit_session(db, session_id: int) -> None:
        stmt = select(FileEditSession).where(FileEditSession.id == session_id)
        result = await db.execute(stmt)
        session = result.scalars().first()
        if session:
            session.is_active = False
            db.add(session)
            await db.commit()

    @staticmethod
    async def end_all_active_sessions(db) -> int:
        stmt = select(FileEditSession).where(FileEditSession.is_active == True)  # noqa: E712
        result = await db.execute(stmt)
        sessions = result.scalars().all()
        for session in sessions:
            session.is_active = False
            db.add(session)
        if sessions:
            await db.commit()
        return len(sessions)

    @staticmethod
    async def sync_live_map_from_github(db, pull_requests: list[dict]) -> int:
        """Rebuild Live Editing Map from real open PR file lists (GitHub authors)."""
        await CodeWatchAgent.end_all_active_sessions(db)
        created = 0
        for idx, pr in enumerate(pull_requests):
            color = GITHUB_AVATAR_COLORS[idx % len(GITHUB_AVATAR_COLORS)]
            dev = await CodeWatchAgent.get_or_create_developer(db, pr["author"], avatar_color=color)
            branch = pr.get("branch") or "head"
            # Live Editing Map time = GitHub PR created_at (when PR was raised)
            pr_time = parse_github_time(pr.get("created_at")) or datetime.utcnow()
            for file_path in (pr.get("files") or [])[:8]:
                await CodeWatchAgent.start_edit_session(
                    db,
                    developer_id=dev.id,
                    file_path=file_path,
                    function_name=f"PR #{pr['number']} · {branch}",
                    started_at=pr_time,
                )
                created += 1
        return created

    @staticmethod
    async def get_active_sessions(db, github_only: bool = True) -> list[FileEditSession]:
        stmt = select(FileEditSession).where(FileEditSession.is_active == True)  # noqa: E712
        result = await db.execute(stmt)
        sessions = result.scalars().all()
        if not github_only:
            return sessions
        filtered = []
        for session in sessions:
            dev = await db.get(Developer, session.developer_id)
            if dev and dev.name in DEMO_DEV_NAMES:
                continue
            filtered.append(session)
        return filtered
