"""Workflow runtime, invitation tokens, milestone approvals

Revision ID: 003
Revises: 002
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # workflow_stages: buyer approval gate flag
    op.add_column(
        "workflow_stages",
        sa.Column("requires_buyer_approval", sa.Boolean(), nullable=False, server_default="false"),
    )

    # workflow_transitions: optional condition type ('approval' | null)
    op.add_column(
        "workflow_transitions",
        sa.Column("condition_type", sa.String(50), nullable=True),
    )

    # workflow_templates: tenant-owned templates need developer_id
    op.add_column(
        "workflow_templates",
        sa.Column("developer_id", sa.String(), nullable=True),
    )

    # project_types: tenant-owned types + updated_at
    op.add_column(
        "project_types",
        sa.Column("developer_id", sa.String(), nullable=True),
    )
    op.add_column(
        "project_types",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # milestone_approvals: buyer sign-off records
    op.create_table(
        "milestone_approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "milestone_id",
            sa.String(),
            sa.ForeignKey("milestones.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "buyer_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(20), nullable=False),  # approved | rejected
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_milestone_approvals_milestone", "milestone_approvals", ["milestone_id"])

    # developer_members: invitation token flow
    op.add_column(
        "developer_members",
        sa.Column("invitation_token", sa.String(64), nullable=True, unique=True),
    )
    op.add_column(
        "developer_members",
        sa.Column("invitation_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "developer_members",
        sa.Column("invitation_status", sa.String(20), nullable=False, server_default="active"),
    )


def downgrade() -> None:
    op.drop_column("developer_members", "invitation_status")
    op.drop_column("developer_members", "invitation_token_expires_at")
    op.drop_column("developer_members", "invitation_token")
    op.drop_table("milestone_approvals")
    op.drop_column("project_types", "updated_at")
    op.drop_column("project_types", "developer_id")
    op.drop_column("workflow_templates", "developer_id")
    op.drop_column("workflow_transitions", "condition_type")
    op.drop_column("workflow_stages", "requires_buyer_approval")
