"""Move subscriptions to be scoped per-project instead of per-developer

A developer can run different projects on different subscription tiers, so
the subscription fields that used to live only on `developers` are added to
`projects` too (additive — the developer-level columns are left in place,
unused going forward, so currently-deployed code reading them keeps working
until it's redeployed). Existing projects are backfilled from their
developer's current subscription, since today every project under a
developer effectively shares one subscription.

Revision ID: 011
Revises: 010
Create Date: 2026-06-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("subscription_tier", sa.String(50), nullable=False, server_default="trial"))
    op.add_column("projects", sa.Column("subscription_status", sa.String(50), nullable=False, server_default="active"))
    op.add_column("projects", sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscription_payments", sa.Column("project_id", sa.String(), nullable=True))
    op.create_index("ix_subscription_payments_project_id", "subscription_payments", ["project_id"])

    op.execute("""
        UPDATE projects
        SET subscription_tier = d.subscription_tier,
            subscription_status = d.subscription_status,
            subscription_expires_at = d.subscription_expires_at,
            trial_ends_at = d.trial_ends_at
        FROM developers d
        WHERE projects.developer_id = d.id
    """)


def downgrade() -> None:
    op.drop_index("ix_subscription_payments_project_id", table_name="subscription_payments")
    op.drop_column("subscription_payments", "project_id")
    op.drop_column("projects", "trial_ends_at")
    op.drop_column("projects", "subscription_expires_at")
    op.drop_column("projects", "subscription_status")
    op.drop_column("projects", "subscription_tier")
