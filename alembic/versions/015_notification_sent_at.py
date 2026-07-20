"""Add notification_log.sent_at

The admin Notification Log's "Sent At" column had no backing field — only
created_at (row-insert time) existed. Adds a real sent_at, populated at the
moment the email send actually completes.

Revision ID: 015
Revises: 014
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notification_log", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_log", "sent_at")
