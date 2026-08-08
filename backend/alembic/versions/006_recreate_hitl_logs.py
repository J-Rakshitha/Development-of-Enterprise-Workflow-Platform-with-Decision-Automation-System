"""Recreate conflict_action_logs with correct HITL schema (fixes legacy column mismatch).

Revision ID: 006_recreate_hitl_logs
Revises: 005_fix_hitl_log_columns
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_recreate_hitl_logs"
down_revision: Union[str, None] = "005_fix_hitl_log_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "conflict_action_logs" not in tables:
        op.create_table(
            "conflict_action_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("conflict_id", sa.Integer(), sa.ForeignKey("conflict_events.id")),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("previous_status", sa.String(30), nullable=True),
            sa.Column("previous_approval_status", sa.String(30), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("snapshot_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        return

    cols = {c["name"] for c in insp.get_columns("conflict_action_logs")}
    if "action_type" not in cols:
        return

    op.rename_table("conflict_action_logs", "conflict_action_logs_legacy")
    op.create_table(
        "conflict_action_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conflict_id", sa.Integer(), sa.ForeignKey("conflict_events.id")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("previous_status", sa.String(30), nullable=True),
        sa.Column("previous_approval_status", sa.String(30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        """
        INSERT INTO conflict_action_logs
            (id, conflict_id, user_id, action, previous_status, previous_approval_status, note, snapshot_json, created_at)
        SELECT
            id, conflict_id, user_id,
            COALESCE(action, action_type, 'unknown'),
            previous_status,
            COALESCE(previous_approval_status, previous_approval),
            note, snapshot_json, created_at
        FROM conflict_action_logs_legacy
        """
    )
    op.drop_table("conflict_action_logs_legacy")


def downgrade() -> None:
    pass
