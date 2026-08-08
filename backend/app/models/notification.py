"""
Team notification records — persisted delivery log for the Notification Agent.
Supports WebSocket (live dashboard), email, and simulated email when SMTP is not configured.
"""
from datetime import datetime
from sqlalchemy import String, Text, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TeamNotification(Base):
    __tablename__ = "team_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(30))  # websocket | email | email_simulated | slack | teams
    event_type: Mapped[str] = mapped_column(String(50))  # conflict_detected | conflict_resolved | incident_created
    module: Mapped[str] = mapped_column(String(30))  # dev_collab | aiops
    recipient: Mapped[str] = mapped_column(String(150))
    subject: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    related_entity_id: Mapped[int] = mapped_column(Integer, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
