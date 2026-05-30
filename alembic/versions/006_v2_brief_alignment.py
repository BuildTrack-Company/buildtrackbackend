"""v2 brief alignment: visibility pages, credibility profile, inquiries, tiers

Revision ID: 006
Revises: 005
Create Date: 2026-05-31 00:00:00.000000

Additive only. Uses IF NOT EXISTS so it is safe to re-run and never breaks
existing data. Adds visibility-page fields, developer credibility profile,
construction-update fields, the inquiries + visibility_page_views tables,
the subscription_tier_limits config table, and remaps legacy tier names.
"""
from typing import Sequence, Union
import re
from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "project"


def upgrade() -> None:
    conn = op.get_bind()

    # ── projects: visibility-page fields ─────────────────────────────────────
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS slug VARCHAR(255)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS visibility_description TEXT")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS visibility_tagline VARCHAR(500)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS starting_price VARCHAR(100)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS construction_progress INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS health_status VARCHAR(50) NOT NULL DEFAULT 'on_schedule'")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS activity_overdue_threshold_days INTEGER NOT NULL DEFAULT 14")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS visibility_page_views INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS visibility_page_published BOOLEAN NOT NULL DEFAULT false")

    # ── developers: credibility profile ──────────────────────────────────────
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS contact_name VARCHAR(255)")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS years_operating INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS projects_completed INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS active_developments INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS avg_update_frequency_days DOUBLE PRECISION")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS update_consistency_pct DOUBLE PRECISION")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS company_overview TEXT")

    # ── uploads (Construction Update): title/category/progress + GPS result ──
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS title VARCHAR(255)")
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS category VARCHAR(100)")
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS progress_at_upload INTEGER")
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS distance_from_site_m DOUBLE PRECISION")
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS within_boundary BOOLEAN NOT NULL DEFAULT false")

    # ── inquiries (leads) ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS inquiries (
            id            VARCHAR PRIMARY KEY,
            project_id    VARCHAR NOT NULL,
            developer_id  VARCHAR NOT NULL,
            first_name    VARCHAR(255) NOT NULL,
            last_name     VARCHAR(255) NOT NULL,
            email         VARCHAR(320) NOT NULL,
            phone         VARCHAR(50),
            location      VARCHAR(255),
            message       TEXT,
            source        VARCHAR(50) NOT NULL DEFAULT 'visibility_page',
            seen_by_developer BOOLEAN NOT NULL DEFAULT false,
            seen_at       TIMESTAMPTZ,
            converted_at  TIMESTAMPTZ,
            ip_address    VARCHAR(64),
            user_agent    TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_inquiry_project_email ON inquiries(project_id, email)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_inquiries_developer ON inquiries(developer_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_inquiries_unseen ON inquiries(project_id) WHERE seen_by_developer = false")

    # ── visibility_page_views (analytics) ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS visibility_page_views (
            id               VARCHAR PRIMARY KEY,
            project_id       VARCHAR NOT NULL,
            session_id       VARCHAR(255) NOT NULL,
            country_code     VARCHAR(8),
            duration_seconds INTEGER,
            referrer         TEXT,
            viewed_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_vpv_project_time ON visibility_page_views(project_id, viewed_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_vpv_country ON visibility_page_views(project_id, country_code)")

    # ── subscription_tier_limits config ──────────────────────────────────────
    # A legacy config table by this name (with starter/growth/scale tiers) is
    # not referenced by any application code or FK, so we replace it with the
    # v2 brief schema. Safe: it holds only default config rows.
    op.execute("DROP TABLE IF EXISTS subscription_tier_limits")
    op.execute("""
        CREATE TABLE IF NOT EXISTS subscription_tier_limits (
            tier                  VARCHAR PRIMARY KEY,
            max_units             INTEGER,
            monthly_fee_kes       NUMERIC(10,2) NOT NULL DEFAULT 0,
            max_projects          INTEGER,
            max_photos_per_upload INTEGER NOT NULL DEFAULT 20,
            max_storage_gb        INTEGER NOT NULL DEFAULT 50,
            max_emails_per_month  INTEGER NOT NULL DEFAULT 5000
        )
    """)
    op.execute("""
        INSERT INTO subscription_tier_limits
            (tier, max_units, monthly_fee_kes, max_projects, max_photos_per_upload, max_storage_gb, max_emails_per_month)
        VALUES
            ('trial',       80, 0,     1,    10, 5,   1000),
            ('small',       80, 20000, 3,    20, 20,  3000),
            ('medium',     200, 32000, 5,    20, 50,  8000),
            ('large',      400, 52000, 10,   25, 100, 15000),
            ('enterprise', NULL, 75000, NULL, 30, 200, 30000)
        ON CONFLICT (tier) DO UPDATE SET
            max_units = EXCLUDED.max_units,
            monthly_fee_kes = EXCLUDED.monthly_fee_kes,
            max_projects = EXCLUDED.max_projects,
            max_photos_per_upload = EXCLUDED.max_photos_per_upload,
            max_storage_gb = EXCLUDED.max_storage_gb,
            max_emails_per_month = EXCLUDED.max_emails_per_month
    """)

    # ── remap legacy tier names to the v2 brief tiers ────────────────────────
    op.execute("UPDATE developers SET subscription_tier = 'small'  WHERE subscription_tier = 'starter'")
    op.execute("UPDATE developers SET subscription_tier = 'medium' WHERE subscription_tier = 'growth'")
    op.execute("UPDATE developers SET subscription_tier = 'large'  WHERE subscription_tier IN ('scale', 'professional')")

    # ── backfill slugs for existing projects (kebab-case + uniqueness) ───────
    rows = conn.execute(sa.text(
        "SELECT id, name FROM projects WHERE slug IS NULL OR slug = ''"
    )).fetchall()
    used = {r[0] for r in conn.execute(sa.text(
        "SELECT slug FROM projects WHERE slug IS NOT NULL AND slug <> ''"
    )).fetchall()}
    for pid, name in rows:
        base = _slugify(name)
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base}-{n}"
            n += 1
        used.add(candidate)
        conn.execute(
            sa.text("UPDATE projects SET slug = :slug WHERE id = :id"),
            {"slug": candidate, "id": pid},
        )

    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_slug ON projects(slug)")


def downgrade() -> None:
    # Additive migration; columns/tables are left in place on downgrade.
    pass
