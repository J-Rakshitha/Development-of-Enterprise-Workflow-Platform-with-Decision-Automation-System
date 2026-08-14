"""
Data models for Module 2: AIOps Automated Incident Response.
"""
from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    service_name: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(10), default="P3")  # P1 | P2 | P3
    status: Mapped[str] = mapped_column(String(30), default="open")  # open | auto_resolved | escalated | closed
    root_cause: Mapped[str] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    mttr_seconds: Mapped[int] = mapped_column(nullable=True)  # Mean Time To Resolve
    linked_commit_id: Mapped[int] = mapped_column(ForeignKey("commit_logs.id"), nullable=True)
    external_references: Mapped[str] = mapped_column(Text, nullable=True)  # JSON list from ExternalLookupAgent
    sla_minutes: Mapped[int] = mapped_column(nullable=True)
    sla_deadline: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    escalated_to: Mapped[str] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="ingest")  # webhook | monitoring | ingest | simulate | legacy
    triggered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    actions: Mapped[list["RemediationAction"]] = relationship(back_populates="incident")


class RemediationAction(Base):
    __tablename__ = "remediation_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"))
    action_type: Mapped[str] = mapped_column(String(100))  # e.g. restart_service, clear_cache
    performed_by: Mapped[str] = mapped_column(String(50), default="Remediation Agent")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped["Incident"] = relationship(back_populates="actions")


class AgentDecisionLog(Base):
    """
    Explainable-AI trail: every decision any agent makes (either module)
    gets recorded here so the dashboard can show a step-by-step reasoning trace.
    """
    __tablename__ = "agent_decision_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(100))
    module: Mapped[str] = mapped_column(String(30))  # dev_collab | aiops
    related_entity_id: Mapped[int] = mapped_column(nullable=True)
    decision_summary: Mapped[str] = mapped_column(Text)
    used_llm: Mapped[bool] = mapped_column(Boolean, default=False)  # True=LLM, False=rule-based fallback
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
