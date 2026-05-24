"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("email_verified", sa.Boolean(), default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # developers table
    op.create_table(
        "developers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, unique=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("subscription_tier", sa.String(50), default="trial", nullable=False),
        sa.Column("subscription_status", sa.String(50), default="active", nullable=False),
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("website", sa.String(255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_developers_user_id", "developers", ["user_id"])

    # projects table
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("developer_id", sa.String(), nullable=False),
        sa.Column("project_code", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location_name", sa.String(255), nullable=True),
        sa.Column("site_latitude", sa.Float(), nullable=True),
        sa.Column("site_longitude", sa.Float(), nullable=True),
        sa.Column("gps_radius_metres", sa.Float(), default=100.0, nullable=False),
        sa.Column("total_units", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), default="planning", nullable=False),
        sa.Column("cover_image_url", sa.Text(), nullable=True),
        sa.Column("estimated_completion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_public", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["developer_id"], ["developers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_projects_developer_id", "projects", ["developer_id"])
    op.create_index("ix_projects_project_code", "projects", ["project_code"])

    # milestones table
    op.create_table(
        "milestones",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), default="pending", nullable=False),
        sa.Column("expected_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delay_reason", sa.Text(), nullable=True),
        sa.Column("delay_new_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_milestones_project_id", "milestones", ["project_id"])

    # upload_sessions table
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("developer_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("capture_latitude", sa.Float(), nullable=False),
        sa.Column("capture_longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=False),
        sa.Column("photo_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_upload_sessions_developer_id", "upload_sessions", ["developer_id"])
    op.create_index("ix_upload_sessions_project_id", "upload_sessions", ["project_id"])

    # uploads table
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("developer_id", sa.String(), nullable=False),
        sa.Column("milestone_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("upload_session_id", sa.String(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("capture_latitude", sa.Float(), nullable=True),
        sa.Column("capture_longitude", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("gps_validated", sa.Boolean(), default=False, nullable=False),
        sa.Column("photo_count", sa.Integer(), default=0, nullable=False),
        sa.Column("status", sa.String(50), default="pending", nullable=False),
        sa.Column("flag_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("notification_fanout_status", sa.String(50), default="pending", nullable=False),
        sa.Column("notification_fanout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["developer_id"], ["developers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_uploads_project_id", "uploads", ["project_id"])
    op.create_index("ix_uploads_developer_id", "uploads", ["developer_id"])
    op.create_index("ix_uploads_idempotency_key", "uploads", ["idempotency_key"])

    # photos table
    op.create_table(
        "photos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("upload_id", sa.String(), nullable=False),
        sa.Column("cloudinary_public_id", sa.String(500), nullable=False),
        sa.Column("cloudinary_url", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("capture_latitude", sa.Float(), nullable=True),
        sa.Column("capture_longitude", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("exif_data", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), default=0, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_photos_upload_id", "photos", ["upload_id"])

    # buyers table
    op.create_table(
        "buyers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("unit_number", sa.String(50), nullable=True),
        sa.Column("invitation_token_hash", sa.String(255), nullable=True),
        sa.Column("invitation_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invitation_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_email", sa.Boolean(), default=True, nullable=False),
        sa.Column("notification_sms", sa.Boolean(), default=False, nullable=False),
        sa.Column("notification_whatsapp", sa.Boolean(), default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_buyers_project_id", "buyers", ["project_id"])
    op.create_index("ix_buyers_email", "buyers", ["email"])
    op.create_index("ix_buyers_user_id", "buyers", ["user_id"])
    op.create_index("ix_buyers_invitation_token_hash", "buyers", ["invitation_token_hash"])

    # auth_token_deny_list table
    op.create_table(
        "auth_token_deny_list",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("jti", sa.String(255), nullable=False, unique=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_token_deny_list_jti", "auth_token_deny_list", ["jti"])
    op.create_index("ix_auth_token_deny_list_user_id", "auth_token_deny_list", ["user_id"])

    # password_reset_tokens table
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"])

    # notification_log table
    op.create_table(
        "notification_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("upload_id", sa.String(), nullable=True),
        sa.Column("buyer_id", sa.String(), nullable=True),
        sa.Column("developer_id", sa.String(), nullable=True),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("template_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), default="sent", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_log_upload_id", "notification_log", ["upload_id"])
    op.create_index("ix_notification_log_buyer_id", "notification_log", ["buyer_id"])

    # audit_log table
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("actor_role", sa.String(50), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("developer_id", sa.String(), nullable=True),
        sa.Column("before_state", sa.Text(), nullable=True),
        sa.Column("after_state", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_developer_id", "audit_log", ["developer_id"])

    # admin_ip_allowlist table
    op.create_table(
        "admin_ip_allowlist",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ip_address", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # webhook_events table
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhook_events_event_id", "webhook_events", ["event_id"])


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("admin_ip_allowlist")
    op.drop_table("audit_log")
    op.drop_table("notification_log")
    op.drop_table("password_reset_tokens")
    op.drop_table("auth_token_deny_list")
    op.drop_table("buyers")
    op.drop_table("photos")
    op.drop_table("uploads")
    op.drop_table("upload_sessions")
    op.drop_table("milestones")
    op.drop_table("projects")
    op.drop_table("developers")
    op.drop_table("users")
