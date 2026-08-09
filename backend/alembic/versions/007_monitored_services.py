"""Add monitored_services table for admin-managed probe targets.

Revision ID: 007_monitored_services
Revises: 006_recreate_hitl_logs
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_monitored_services"
down_revision: Union[str, None] = "006_recreate_hitl_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "monitored_services" in insp.get_table_names():
        return
    op.create_table(
        "monitored_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_monitored_services_name", "monitored_services", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_monitored_services_name", table_name="monitored_services")
    op.drop_table("monitored_services")
