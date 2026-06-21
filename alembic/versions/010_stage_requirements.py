"""Add requires_photo/requires_file to workflow_stages

Revision ID: 010
Revises: 009
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workflow_stages", sa.Column("requires_photo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("workflow_stages", sa.Column("requires_file", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("workflow_stages", "requires_file")
    op.drop_column("workflow_stages", "requires_photo")
