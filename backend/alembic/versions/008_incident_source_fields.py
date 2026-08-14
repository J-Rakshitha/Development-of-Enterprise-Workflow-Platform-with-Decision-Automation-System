"""Add source and triggered_by to incidents for enterprise AIOps tracking.

Revision ID: 008_incident_source
Revises: 007_monitored_services
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_incident_source"
down_revision: Union[str, None] = "007_monitored_services"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("incidents")}
    if "source" not in cols:
        op.add_column("incidents", sa.Column("source", sa.String(30), nullable=False, server_default="legacy"))
    if "triggered_by" not in cols:
        op.add_column("incidents", sa.Column("triggered_by", sa.String(100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("incidents")}
    if "triggered_by" in cols:
        op.drop_column("incidents", "triggered_by")
    if "source" in cols:
        op.drop_column("incidents", "source")
