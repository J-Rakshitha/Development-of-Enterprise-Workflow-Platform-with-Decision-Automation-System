"""ChatGPT-style chat sessions with follow-up Q&A."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dev_collab import ConflictEvent, FileEditSession
from app.models.incident import Incident
from app.models.user import User
from app.models.workflow import ChatMessage, ChatSession


async def list_sessions(db: AsyncSession, user: User) -> list[dict]:
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    result = await db.execute(stmt)
    return [
        {"id": s.id, "title": s.title, "created_at": s.created_at, "updated_at": s.updated_at}
        for s in result.scalars().all()
    ]


async def create_session(db: AsyncSession, user: User, title: str = "New conversation") -> dict:
    safe_title = str(title or "New conversation").strip() or "New conversation"
    session = ChatSession(user_id=user.id, title=safe_title[:200])
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"id": session.id, "title": session.title, "created_at": session.created_at}


async def get_messages(db: AsyncSession, user: User, session_id: int) -> list[dict]:
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise ValueError("Session not found")

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    return [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in result.scalars().all()]


async def _build_answer(db: AsyncSession, question: str) -> str:
    q = question.lower()
    conflict_count = await db.scalar(select(func.count()).select_from(ConflictEvent))
    open_conflicts = await db.scalar(
        select(func.count()).select_from(ConflictEvent).where(ConflictEvent.status == "predicted")
    )
    incident_count = await db.scalar(select(func.count()).select_from(Incident))
    open_incidents = await db.scalar(
        select(func.count()).select_from(Incident).where(Incident.status.in_(["open", "escalated"]))
    )
    sessions = await db.scalar(
        select(func.count()).select_from(FileEditSession).where(FileEditSession.is_active.is_(True))
    )

    if "conflict" in q:
        return (
            f"There are {conflict_count or 0} total predicted/resolved conflicts in the system, "
            f"with {open_conflicts or 0} still open. Use Dev-Collaboration to review and approve AI suggestions."
        )
    if "incident" in q or "aiops" in q:
        return (
            f"The platform tracks {incident_count or 0} incidents ({open_incidents or 0} open). "
            f"AIOps agents classify severity, diagnose root cause, and run remediation tools."
        )
    if "dev-collab" in q or "dev collab" in q or "merge" in q:
        return (
            "Dev-Collaboration predicts merge conflicts before they happen, runs semantic analysis, "
            "and requires human approval before resolving — you stay in control via HITL."
        )
    if "agent" in q or "coordinator" in q:
        return (
            "23 specialized agents coordinate Dev-Collaboration and AIOps. The Coordinator Agent "
            "links production incidents back to risky merges and logs all decisions."
        )
    return (
        f"Enterprise Workflow Platform summary: {sessions or 0} active edit sessions, "
        f"{open_conflicts or 0} open conflicts, {open_incidents or 0} open incidents. "
        f"Ask about conflicts, incidents, Dev-Collab, or agents for more detail."
    )


async def ask_question(db: AsyncSession, user: User, session_id: int, question: str) -> dict:
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise ValueError("Session not found")

    db.add(ChatMessage(session_id=session_id, role="user", content=question))
    answer = await _build_answer(db, question)
    db.add(ChatMessage(session_id=session_id, role="assistant", content=answer))
    session.updated_at = datetime.utcnow()
    if session.title == "New conversation" and len(question) > 10:
        session.title = question[:60] + ("..." if len(question) > 60 else "")
    await db.commit()
    return {"answer": answer, "session_id": session_id}
