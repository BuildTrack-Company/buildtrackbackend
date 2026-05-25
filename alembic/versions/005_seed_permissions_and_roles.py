"""Seed permissions and system roles for RBAC enforcement

Revision ID: 005
Revises: 004
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = datetime(2026, 5, 25, 0, 0, 0, tzinfo=timezone.utc)

# ── Permission IDs ────────────────────────────────────────────────────────────
PERMS = {
    # projects
    "projects:read":    "perm_proj_read",
    "projects:create":  "perm_proj_create",
    "projects:update":  "perm_proj_update",
    "projects:delete":  "perm_proj_delete",
    # milestones
    "milestones:read":   "perm_mile_read",
    "milestones:update": "perm_mile_update",
    # photos / uploads
    "photos:read":   "perm_phot_read",
    "photos:upload": "perm_phot_upload",
    # buyers
    "buyers:read":   "perm_buyr_read",
    "buyers:create": "perm_buyr_create",
    "buyers:delete": "perm_buyr_delete",
    "buyers:notify": "perm_buyr_notify",
    # team members
    "team:read":   "perm_team_read",
    "team:invite": "perm_team_invite",
    "team:manage": "perm_team_manage",
    # roles & rbac
    "roles:read":   "perm_role_read",
    "roles:manage": "perm_role_manage",
    # workflow
    "workflow:read":    "perm_wkfl_read",
    "workflow:advance": "perm_wkfl_advance",
    # billing
    "billing:read": "perm_bill_read",
    # tenant settings
    "settings:read":   "perm_sett_read",
    "settings:update": "perm_sett_update",
    # project types / workflow templates
    "project_types:read":   "perm_ptype_read",
    "project_types:manage": "perm_ptype_manage",
}

# ── Role IDs ──────────────────────────────────────────────────────────────────
ROLE_PROJECT_MANAGER   = "role_project_manager"
ROLE_SITE_VIEWER       = "role_site_viewer"
ROLE_BUYER_MANAGER     = "role_buyer_manager"
ROLE_FINANCE_MANAGER   = "role_finance_manager"
ROLE_ORG_FULL_ACCESS   = "role_org_full_access"

ROLES = [
    (ROLE_PROJECT_MANAGER, "Project Manager",
     "Manage projects, milestones, photos, and advance workflow stages"),
    (ROLE_SITE_VIEWER, "Site Viewer",
     "Read-only access to projects, milestones, photos, and workflow"),
    (ROLE_BUYER_MANAGER, "Buyer Relations Manager",
     "Invite and manage buyers, send notifications"),
    (ROLE_FINANCE_MANAGER, "Finance Manager",
     "Access billing information and tenant settings"),
    (ROLE_ORG_FULL_ACCESS, "Organisation Full Access",
     "All permissions — for trusted team members who need full developer access"),
]

# ── Role-to-permissions mapping ───────────────────────────────────────────────
ROLE_PERMISSIONS = {
    ROLE_PROJECT_MANAGER: [
        "projects:read", "projects:create", "projects:update",
        "milestones:read", "milestones:update",
        "photos:read", "photos:upload",
        "buyers:read",
        "workflow:read", "workflow:advance",
        "billing:read",
        "settings:read",
        "project_types:read",
        "team:read",
        "roles:read",
    ],
    ROLE_SITE_VIEWER: [
        "projects:read",
        "milestones:read",
        "photos:read",
        "workflow:read",
        "project_types:read",
        "buyers:read",
        "team:read",
    ],
    ROLE_BUYER_MANAGER: [
        "projects:read",
        "milestones:read",
        "photos:read",
        "buyers:read", "buyers:create", "buyers:delete", "buyers:notify",
        "workflow:read",
    ],
    ROLE_FINANCE_MANAGER: [
        "projects:read",
        "billing:read",
        "settings:read", "settings:update",
    ],
    ROLE_ORG_FULL_ACCESS: list(PERMS.keys()),  # every permission
}


def upgrade() -> None:
    conn = op.get_bind()

    # ── Add condition_type column to workflow_transitions if missing ───────────
    has_col = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='workflow_transitions' AND column_name='condition_type'"
    )).fetchone()
    if not has_col:
        op.add_column(
            "workflow_transitions",
            sa.Column("condition_type", sa.String(50), nullable=True),
        )

    # ── Seed permissions ──────────────────────────────────────────────────────
    perm_rows = []
    for key, pid in PERMS.items():
        resource, action = key.split(":", 1)
        perm_rows.append({
            "id": pid,
            "name": key,
            "description": f"Permission to {action} {resource}",
            "resource": resource,
            "action": action,
            "created_at": NOW,
        })

    # Insert only if not already present (idempotent)
    existing_ids = {row[0] for row in conn.execute(sa.text("SELECT id FROM permissions")).fetchall()}
    for row in perm_rows:
        if row["id"] not in existing_ids:
            conn.execute(
                sa.text(
                    "INSERT INTO permissions (id, name, description, resource, action, created_at) "
                    "VALUES (:id, :name, :description, :resource, :action, :created_at)"
                ),
                row,
            )

    # ── Seed roles ────────────────────────────────────────────────────────────
    existing_role_ids = {row[0] for row in conn.execute(sa.text("SELECT id FROM roles")).fetchall()}
    for role_id, name, description in ROLES:
        if role_id not in existing_role_ids:
            conn.execute(
                sa.text(
                    "INSERT INTO roles (id, name, description, is_system, created_at, updated_at) "
                    "VALUES (:id, :name, :description, true, :now, :now)"
                ),
                {"id": role_id, "name": name, "description": description, "now": NOW},
            )

    # ── Seed role_permissions ─────────────────────────────────────────────────
    existing_rp = {
        (row[0], row[1])
        for row in conn.execute(sa.text("SELECT role_id, permission_id FROM role_permissions")).fetchall()
    }
    rp_counter = 0
    for role_id, perm_keys in ROLE_PERMISSIONS.items():
        for perm_key in perm_keys:
            perm_id = PERMS[perm_key]
            if (role_id, perm_id) not in existing_rp:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (id, role_id, permission_id, created_at) "
                        "VALUES (:id, :role_id, :permission_id, :now)"
                    ),
                    {
                        "id": f"rp_{role_id}_{perm_id}",
                        "role_id": role_id,
                        "permission_id": perm_id,
                        "now": NOW,
                    },
                )
                rp_counter += 1


def downgrade() -> None:
    conn = op.get_bind()
    role_ids = list({r[0] for r in [
        (ROLE_PROJECT_MANAGER,), (ROLE_SITE_VIEWER,), (ROLE_BUYER_MANAGER,),
        (ROLE_FINANCE_MANAGER,), (ROLE_ORG_FULL_ACCESS,),
    ]})
    perm_ids = list(PERMS.values())

    # Remove seeded role_permissions
    for rid in role_ids:
        conn.execute(sa.text("DELETE FROM role_permissions WHERE role_id = :rid"), {"rid": rid})

    # Remove seeded roles
    for rid in role_ids:
        conn.execute(sa.text("DELETE FROM roles WHERE id = :rid"), {"rid": rid})

    # Remove seeded permissions
    for pid in perm_ids:
        conn.execute(sa.text("DELETE FROM permissions WHERE id = :pid"), {"pid": pid})
