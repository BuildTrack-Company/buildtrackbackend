"""Make developer_members.user_id nullable and add invited_email

Revision ID: 004
Revises: 003
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow user_id to be NULL for pending invitations (user hasn't accepted yet)
    op.alter_column("developer_members", "user_id", nullable=True)

    # Store invitee email on pending records so accept_invitation can create user
    op.add_column(
        "developer_members",
        sa.Column("invited_email", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("developer_members", "invited_email")
    op.alter_column("developer_members", "user_id", nullable=False)
