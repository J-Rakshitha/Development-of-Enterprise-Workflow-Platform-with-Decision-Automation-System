"""Enterprise workflow — HITL, user repos, chat, audit trail.

Revision ID: 003_enterprise_workflow
Revises: 002_enterprise_intelligence
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_enterprise_workflow"
down_revision: Union[str, None] = "002_enterprise_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    conflict_cols = _columns("conflict_events")
    for col, col_type in [
        ("approval_status", sa.String(30)),
        ("resolved_by_user_id", sa.Integer()),
        ("updated_by_user_id", sa.Integer()),
        ("owner_user_id", sa.Integer()),
        ("resolved_by_name", sa.String(100)),
        ("user_note", sa.Text()),
    ]:
        if col not in conflict_cols:
            op.add_column("conflict_events", sa.Column(col, col_type, nullable=True))

    if "user_repos" not in tables:
        op.create_table(
            "user_repos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), unique=True),
            sa.Column("repo_url", sa.String(500), nullable=False),
            sa.Column("repo_owner", sa.String(100), nullable=False),
            sa.Column("repo_name", sa.String(200), nullable=False),
            sa.Column("symbols_indexed", sa.Integer(), default=0),
            sa.Column("conflicts_found", sa.Integer(), default=0),
            sa.Column("last_scanned_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

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
    else:
        log_cols = _columns("conflict_action_logs")
        for col, col_type in [
            ("action", sa.String(30)),
            ("previous_status", sa.String(30)),
            ("previous_approval_status", sa.String(30)),
            ("note", sa.Text()),
            ("snapshot_json", sa.Text()),
            ("created_at", sa.DateTime()),
        ]:
            if col not in log_cols:
                op.add_column("conflict_action_logs", sa.Column(col, col_type, nullable=True))

    if "chat_sessions" not in tables:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("title", sa.String(200), default="New conversation"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "chat_messages" not in tables:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id")),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("conflict_action_logs")
    op.drop_table("user_repos")
    for col in ("user_note", "resolved_by_name", "owner_user_id", "updated_by_user_id", "resolved_by_user_id", "approval_status"):
        if col in _columns("conflict_events"):
            op.drop_column("conflict_events", col)
