"""Dynamic workflows, RBAC, multi-user orgs, settings

Revision ID: 002
Revises: 001
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── project_types ────────────────────────────────────────────────────────
    op.create_table(
        "project_types",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── workflow_templates ───────────────────────────────────────────────────
    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_type_id", sa.String(), sa.ForeignKey("project_types.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), default=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── workflow_stages ──────────────────────────────────────────────────────
    op.create_table(
        "workflow_stages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workflow_template_id", sa.String(), sa.ForeignKey("workflow_templates.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("expected_duration_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── workflow_transitions ─────────────────────────────────────────────────
    op.create_table(
        "workflow_transitions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workflow_template_id", sa.String(), sa.ForeignKey("workflow_templates.id"), nullable=False, index=True),
        sa.Column("from_stage_id", sa.String(), sa.ForeignKey("workflow_stages.id"), nullable=True),
        sa.Column("to_stage_id", sa.String(), sa.ForeignKey("workflow_stages.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── permissions ──────────────────────────────────────────────────────────
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resource", sa.String(50), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_permissions_resource_action", "permissions", ["resource", "action"])

    # ── roles ────────────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── role_permissions ─────────────────────────────────────────────────────
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("role_id", sa.String(), sa.ForeignKey("roles.id"), nullable=False, index=True),
        sa.Column("permission_id", sa.String(), sa.ForeignKey("permissions.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
    )

    # ── user_role_assignments ────────────────────────────────────────────────
    op.create_table(
        "user_role_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("role_id", sa.String(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("developer_id", sa.String(), nullable=True, index=True),
        sa.Column("granted_by", sa.String(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "role_id", "developer_id", name="uq_user_role_dev"),
    )

    # ── developer_members ────────────────────────────────────────────────────
    op.create_table(
        "developer_members",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("developer_id", sa.String(), sa.ForeignKey("developers.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("org_role", sa.String(50), nullable=False, default="member"),
        sa.Column("invited_by", sa.String(), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("developer_id", "user_id", name="uq_developer_member"),
    )

    # ── tenant_settings ──────────────────────────────────────────────────────
    op.create_table(
        "tenant_settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("developer_id", sa.String(), sa.ForeignKey("developers.id"), nullable=False, index=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("developer_id", "key", name="uq_tenant_setting"),
    )

    # ── system_settings ──────────────────────────────────────────────────────
    op.create_table(
        "system_settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── ALTER projects ────────────────────────────────────────────────────────
    op.add_column("projects", sa.Column("project_type_id", sa.String(), sa.ForeignKey("project_types.id"), nullable=True))
    op.add_column("projects", sa.Column("workflow_template_id", sa.String(), sa.ForeignKey("workflow_templates.id"), nullable=True))
    op.add_column("projects", sa.Column("current_stage_id", sa.String(), sa.ForeignKey("workflow_stages.id"), nullable=True))

    # ── ALTER milestones ──────────────────────────────────────────────────────
    op.add_column("milestones", sa.Column("workflow_stage_id", sa.String(), sa.ForeignKey("workflow_stages.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("milestones", "workflow_stage_id")
    op.drop_column("projects", "current_stage_id")
    op.drop_column("projects", "workflow_template_id")
    op.drop_column("projects", "project_type_id")
    op.drop_table("system_settings")
    op.drop_table("tenant_settings")
    op.drop_table("developer_members")
    op.drop_table("user_role_assignments")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_table("workflow_transitions")
    op.drop_table("workflow_stages")
    op.drop_table("workflow_templates")
    op.drop_table("project_types")
