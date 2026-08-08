"""Milestone 4 — workflow orchestration tables + notification acknowledge.

Revision ID: 004_workflow_orchestration
Revises: 003_enterprise_workflow
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_workflow_orchestration"
down_revision: Union[str, None] = "003_enterprise_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "workflow_definitions" not in tables:
        op.create_table(
            "workflow_definitions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("template_key", sa.String(80), unique=True, index=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("steps_json", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), default=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if "workflow_runs" not in tables:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("definition_id", sa.Integer(), sa.ForeignKey("workflow_definitions.id")),
            sa.Column("template_key", sa.String(80), index=True),
            sa.Column("status", sa.String(30), default="pending"),
            sa.Column("current_step_index", sa.Integer(), default=0),
            sa.Column("started_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("context_json", sa.Text(), default="{}"),
            sa.Column("conflict_id", sa.Integer(), sa.ForeignKey("conflict_events.id"), nullable=True),
            sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "workflow_step_logs" not in tables:
        op.create_table(
            "workflow_step_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id"), index=True),
            sa.Column("step_index", sa.Integer()),
            sa.Column("step_id", sa.String(80)),
            sa.Column("agent_name", sa.String(100)),
            sa.Column("module", sa.String(30)),
            sa.Column("status", sa.String(30), default="pending"),
            sa.Column("output_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), default=0),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )

    if "workflow_jobs" not in tables:
        op.create_table(
            "workflow_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id"), index=True),
            sa.Column("step_index", sa.Integer()),
            sa.Column("job_type", sa.String(50)),
            sa.Column("status", sa.String(30), default="queued"),
            sa.Column("retry_count", sa.Integer(), default=0),
            sa.Column("max_retries", sa.Integer(), default=3),
            sa.Column("scheduled_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
        )

    notif_cols = {c["name"] for c in insp.get_columns("team_notifications")} if "team_notifications" in tables else set()
    if "team_notifications" in tables and "acknowledged" not in notif_cols:
        op.add_column("team_notifications", sa.Column("acknowledged", sa.Boolean(), server_default=sa.false()))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in ("workflow_jobs", "workflow_step_logs", "workflow_runs", "workflow_definitions"):
        if table in tables:
            op.drop_table(table)
    if "team_notifications" in tables:
        cols = {c["name"] for c in insp.get_columns("team_notifications")}
        if "acknowledged" in cols:
            op.drop_column("team_notifications", "acknowledged")
