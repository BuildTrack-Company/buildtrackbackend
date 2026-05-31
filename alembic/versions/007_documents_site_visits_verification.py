"""v2 phase 4: project documents, site visit requests, independent verification

Revision ID: 007
Revises: 006
Create Date: 2026-05-31

Adds:
  - project_documents table (sale agreements, title deeds, certificates)
  - site_visit_requests table (lean booking flow)
  - independent_verification_* columns on projects (third-party spot checks)
All statements are idempotent so the migration is safe to re-run.
"""
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    # ── project_documents ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS project_documents (
            id                   VARCHAR PRIMARY KEY,
            project_id           VARCHAR NOT NULL,
            developer_id         VARCHAR NOT NULL,
            title                VARCHAR(255) NOT NULL,
            document_type        VARCHAR(50) NOT NULL DEFAULT 'custom',
            cloudinary_public_id VARCHAR(500) NOT NULL,
            cloudinary_url       TEXT NOT NULL,
            file_size_bytes      INTEGER,
            mime_type            VARCHAR(100),
            visible_to_buyers    BOOLEAN NOT NULL DEFAULT false,
            uploaded_by_user_id  VARCHAR,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at           TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_documents_project_id ON project_documents (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_documents_developer_id ON project_documents (developer_id)")

    # ── site_visit_requests ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS site_visit_requests (
            id                  VARCHAR PRIMARY KEY,
            project_id          VARCHAR NOT NULL,
            developer_id        VARCHAR NOT NULL,
            requester_user_id   VARCHAR,
            full_name           VARCHAR(255) NOT NULL,
            email               VARCHAR(320) NOT NULL,
            phone               VARCHAR(50) NOT NULL,
            requested_date      DATE NOT NULL,
            preferred_time_slot VARCHAR(20),
            party_size          INTEGER NOT NULL DEFAULT 1,
            purpose             TEXT,
            status              VARCHAR(20) NOT NULL DEFAULT 'requested',
            confirmed_datetime  TIMESTAMPTZ,
            developer_notes     TEXT,
            cancellation_reason TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_site_visit_requests_project_id ON site_visit_requests (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_site_visit_requests_developer_id ON site_visit_requests (developer_id)")

    # ── independent verification on projects ───────────────────────────────────
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS independent_verification_enabled BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_independent_verification_at TIMESTAMPTZ")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_independent_verifier_name VARCHAR(255)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_independent_verifier_outcome VARCHAR(20)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_independent_verifier_notes TEXT")


def downgrade():
    # Additive migration; no-op downgrade (mirrors 006).
    pass
