"""Add project_units table for buyer self-registration unit validation

Developers assign unit numbers up front (bulk via the buyer CSV, or one at a
time via "Add Unit"). When a buyer self-registers with the project code they
must supply a unit number that matches one of these — validated on a
normalised (case/space/dash-insensitive) form. Existing buyer unit numbers are
backfilled so units captured before this table existed still validate.

Revision ID: 013
Revises: 012
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_units",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("unit_number", sa.String(50), nullable=False),
        sa.Column("unit_number_normalized", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_project_units_project_id", "project_units", ["project_id"])
    op.create_index("ix_project_units_unit_number_normalized", "project_units", ["unit_number_normalized"])

    # Backfill from existing buyers' unit numbers so previously-uploaded units
    # keep validating. Normalisation mirrors the app: lower-case, alphanumerics
    # only (strip spaces, dashes, dots, etc.).
    op.execute(
        """
        INSERT INTO project_units (id, project_id, unit_number, unit_number_normalized, created_at)
        SELECT DISTINCT ON (b.project_id, regexp_replace(lower(b.unit_number), '[^a-z0-9]', '', 'g'))
               md5(random()::text || clock_timestamp()::text),
               b.project_id,
               b.unit_number,
               regexp_replace(lower(b.unit_number), '[^a-z0-9]', '', 'g'),
               now()
        FROM buyers b
        WHERE b.unit_number IS NOT NULL
          AND btrim(b.unit_number) <> ''
          AND b.deleted_at IS NULL
          AND regexp_replace(lower(b.unit_number), '[^a-z0-9]', '', 'g') <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_project_units_unit_number_normalized", table_name="project_units")
    op.drop_index("ix_project_units_project_id", table_name="project_units")
    op.drop_table("project_units")
