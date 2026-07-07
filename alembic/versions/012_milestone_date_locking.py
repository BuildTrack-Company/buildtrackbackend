"""Add expected_date_set_at to milestones for 48h date locking

Revision ID: 012
Revises: 011
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "milestones",
        sa.Column("expected_date_set_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("milestones", "expected_date_set_at")
