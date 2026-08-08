"""Milestone 4 — Workflow orchestration models."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    steps_json: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("workflow_definitions.id"))
    template_key: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    started_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    conflict_id: Mapped[int | None] = mapped_column(ForeignKey("conflict_events.id"), nullable=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkflowStepLog(Base):
    __tablename__ = "workflow_step_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String(80))
    agent_name: Mapped[str] = mapped_column(String(100))
    module: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkflowJob(Base):
    __tablename__ = "workflow_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    job_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
