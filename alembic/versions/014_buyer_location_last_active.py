"""Add buyer location + last_active_at

Location is captured at self-registration and shown in the developer buyer list
and admin buyers table. last_active_at records the buyer's most recent sign-in /
portal open, surfaced in the developer and admin portals.

Revision ID: 014
Revises: 013
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("buyers", sa.Column("location", sa.String(255), nullable=True))
    op.add_column("buyers", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("buyers", "last_active_at")
    op.drop_column("buyers", "location")
