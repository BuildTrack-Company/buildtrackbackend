"""Add subscription_payments

Revision ID: 008
Revises: 0957423bbcec
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "0957423bbcec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_payments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("developer_id", sa.String(), nullable=False),
        sa.Column("tier", sa.String(length=50), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_due_kes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount_paid_kes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("method", sa.String(length=30), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_subscription_payments_developer_id"),
        "subscription_payments",
        ["developer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_subscription_payments_developer_id"),
        table_name="subscription_payments",
    )
    op.drop_table("subscription_payments")
