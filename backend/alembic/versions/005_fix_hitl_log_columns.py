"""Repair conflict_action_logs columns on databases created before HITL migration fix.

Revision ID: 005_fix_hitl_log_columns
Revises: 004_workflow_orchestration
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_fix_hitl_log_columns"
down_revision: Union[str, None] = "004_workflow_orchestration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "conflict_action_logs" not in sa.inspect(op.get_bind()).get_table_names():
        return
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


def downgrade() -> None:
    pass
