"""Add photos.media_type (image/video)

Verified site updates can now include video, captured on-site and tied to the
same GPS + timestamp as photos. Adds a media_type discriminator to the photos
table so a single update can mix photos and videos. Existing rows default to
"image", so nothing changes for records uploaded before this.

Revision ID: 016
Revises: 015
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "photos",
        sa.Column("media_type", sa.String(length=20), nullable=False, server_default="image"),
    )


def downgrade() -> None:
    op.drop_column("photos", "media_type")
