"""
Seed development database with test data.
Run: .venv/Scripts/python scripts/seed_dev.py
"""
import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.core.database import async_session_factory
from app.core.security import hash_password
from app.shared.ids import new_id
from app.modules.auth.models import User
from app.modules.developers.models import Developer
from app.modules.projects.models import Project
from app.modules.milestones.models import Milestone
from app.modules.buyers.models import Buyer
from app.modules.uploads.models import Upload, Photo
from app.modules.project_types.models import ProjectType, WorkflowTemplate, WorkflowStage, WorkflowTransition
from app.modules.roles.models import Permission, Role, RolePermission, UserRoleAssignment
from app.modules.members.models import DeveloperMember
from app.modules.settings.models import TenantSetting, SystemSetting


async def seed_project_types(db: AsyncSession) -> dict:
    """Seed 5 system project types and workflow templates. Returns map of template name -> (template, stages)."""
    print("\n--- Project Types & Workflow Templates ---")

    templates_map = {}
    now = datetime.now(timezone.utc)

    project_types_data = [
        {
            "name": "Off-Plan Apartment",
            "description": "Multi-storey residential apartment block",
            "stages": [
                ("Pre-Construction", 1, 60, "Site preparation, permits, and mobilisation"),
                ("Foundation", 2, 90, "Excavation, piling, and foundation slab"),
                ("Superstructure", 3, 180, "Columns, beams, slabs, and stairwells"),
                ("Building Envelope", 4, 90, "Roofing, external walls, windows, and doors"),
                ("Practical Completion", 5, 120, "MEP, finishes, landscaping, and handover"),
            ],
        },
        {
            "name": "Off-Plan Villa/Townhouse",
            "description": "Stand-alone or terraced residential units",
            "stages": [
                ("Pre-Construction", 1, 45, "Permits, soil tests, and site clearing"),
                ("Foundation", 2, 60, "Strip or raft foundation"),
                ("Superstructure", 3, 120, "Walling, roofing structure"),
                ("Building Envelope", 4, 60, "Roof cover, plastering, external works"),
                ("Practical Completion", 5, 90, "Internal finishes and landscaping"),
            ],
        },
        {
            "name": "Commercial Building",
            "description": "Office, retail, or mixed-use commercial development",
            "stages": [
                ("Pre-Construction", 1, 60, "EIA, permits, and design finalisation"),
                ("Foundation & Basement", 2, 120, "Deep foundations and basement structure"),
                ("Superstructure", 3, 240, "Steel or concrete frame and floors"),
                ("Building Envelope & MEP", 4, 120, "Cladding, curtain wall, and services rough-in"),
                ("Fit-Out & Commissioning", 5, 120, "Interior fit-out, testing, and handover"),
            ],
        },
        {
            "name": "Road Construction",
            "description": "Road, highway, or infrastructure project",
            "stages": [
                ("Survey & Design", 1, 60, "Topographic survey and detailed design"),
                ("Earthworks", 2, 90, "Clearing, grubbing, and bulk earthworks"),
                ("Sub-Base & Base Course", 3, 60, "Sub-base compaction and base course laying"),
                ("Surfacing", 4, 45, "Asphalt or concrete paving"),
                ("Drainage & Finishing", 5, 30, "Culverts, kerbs, road markings, and signs"),
            ],
        },
        {
            "name": "Renovation",
            "description": "Refurbishment or extension of existing structure",
            "stages": [
                ("Assessment & Design", 1, 30, "Structural survey and renovation design"),
                ("Demolition & Strip-Out", 2, 30, "Remove finishes and non-structural elements"),
                ("Structural Works", 3, 60, "Any structural repairs or additions"),
                ("Services & Finishes", 4, 60, "MEP, plastering, tiling, and joinery"),
                ("Snagging & Handover", 5, 14, "Final inspections and client handover"),
            ],
        },
    ]

    for pt_data in project_types_data:
        result = await db.execute(select(ProjectType).where(ProjectType.name == pt_data["name"]))
        pt = result.scalar_one_or_none()
        if not pt:
            pt = ProjectType(
                id=new_id(),
                name=pt_data["name"],
                description=pt_data["description"],
                is_system=True,
                created_at=now,
            )
            db.add(pt)
            await db.flush()
            print(f"  Created project type: {pt.name}")
        else:
            print(f"  Exists: {pt.name}")

        # One default template per project type
        tmpl_name = f"{pt_data['name']} Standard"
        result = await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.name == tmpl_name))
        tmpl = result.scalar_one_or_none()
        if not tmpl:
            tmpl = WorkflowTemplate(
                id=new_id(),
                project_type_id=pt.id,
                name=tmpl_name,
                description=f"Standard workflow for {pt_data['name']} projects",
                is_system=True,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(tmpl)
            await db.flush()
            print(f"    Created template: {tmpl.name}")
        else:
            print(f"    Template exists: {tmpl.name}")

        # Stages
        result = await db.execute(select(WorkflowStage).where(WorkflowStage.workflow_template_id == tmpl.id))
        existing_stages = result.scalars().all()
        stages = existing_stages

        if not existing_stages:
            stages = []
            for stage_name, order_index, duration_days, stage_desc in pt_data["stages"]:
                stage = WorkflowStage(
                    id=new_id(),
                    workflow_template_id=tmpl.id,
                    name=stage_name,
                    description=stage_desc,
                    order_index=order_index,
                    expected_duration_days=duration_days,
                    created_at=now,
                )
                db.add(stage)
                stages.append(stage)
            await db.flush()
            print(f"    Created {len(stages)} stages")

        # Transitions (start -> first, and each stage -> next)
        result = await db.execute(
            select(WorkflowTransition).where(WorkflowTransition.workflow_template_id == tmpl.id)
        )
        if not result.scalars().all():
            sorted_stages = sorted(stages, key=lambda s: s.order_index)
            # First transition: null -> first stage
            db.add(WorkflowTransition(
                id=new_id(),
                workflow_template_id=tmpl.id,
                from_stage_id=None,
                to_stage_id=sorted_stages[0].id,
                name="Start",
                created_at=now,
            ))
            for i in range(len(sorted_stages) - 1):
                db.add(WorkflowTransition(
                    id=new_id(),
                    workflow_template_id=tmpl.id,
                    from_stage_id=sorted_stages[i].id,
                    to_stage_id=sorted_stages[i + 1].id,
                    name=f"Advance to {sorted_stages[i + 1].name}",
                    created_at=now,
                ))
            await db.flush()

        templates_map[pt_data["name"]] = (tmpl, sorted(stages, key=lambda s: s.order_index) if not existing_stages else sorted(existing_stages, key=lambda s: s.order_index))

    await db.flush()
    return templates_map


async def seed_permissions_and_roles(db: AsyncSession):
    """Seed permission catalog and 5 system roles."""
    print("\n--- Permissions & Roles ---")
    now = datetime.now(timezone.utc)

    permissions_data = [
        # projects
        ("projects.create", "projects", "create", "Create new projects"),
        ("projects.read", "projects", "read", "View project details"),
        ("projects.update", "projects", "update", "Update project details"),
        ("projects.delete", "projects", "delete", "Delete projects"),
        # uploads
        ("uploads.create", "uploads", "create", "Submit photo uploads"),
        ("uploads.read", "uploads", "read", "View uploads"),
        ("uploads.review", "uploads", "review", "Approve or reject uploads"),
        # milestones
        ("milestones.update", "milestones", "update", "Update milestone status"),
        ("milestones.read", "milestones", "read", "View milestones"),
        # buyers
        ("buyers.invite", "buyers", "invite", "Invite buyers to project"),
        ("buyers.read", "buyers", "read", "View buyer list"),
        # members
        ("members.manage", "members", "manage", "Invite and remove org members"),
        ("members.read", "members", "read", "View org members"),
        # settings
        ("settings.read", "settings", "read", "Read tenant settings"),
        ("settings.update", "settings", "update", "Update tenant settings"),
        # admin
        ("admin.platform", "admin", "platform", "Access admin platform features"),
    ]

    perm_map = {}
    for perm_name, resource, action, desc in permissions_data:
        result = await db.execute(select(Permission).where(Permission.name == perm_name))
        perm = result.scalar_one_or_none()
        if not perm:
            perm = Permission(
                id=new_id(),
                name=perm_name,
                description=desc,
                resource=resource,
                action=action,
                created_at=now,
            )
            db.add(perm)
            await db.flush()
        perm_map[perm_name] = perm

    print(f"  Permissions: {len(perm_map)} ready")

    roles_data = [
        {
            "name": "platform_admin",
            "description": "BuildTrack platform administrator with full access",
            "permissions": list(perm_map.keys()),
        },
        {
            "name": "developer_owner",
            "description": "Developer organisation owner - full control over org",
            "permissions": [
                "projects.create", "projects.read", "projects.update", "projects.delete",
                "uploads.create", "uploads.read",
                "milestones.update", "milestones.read",
                "buyers.invite", "buyers.read",
                "members.manage", "members.read",
                "settings.read", "settings.update",
            ],
        },
        {
            "name": "developer_admin",
            "description": "Developer org admin - manage projects and team but not billing",
            "permissions": [
                "projects.create", "projects.read", "projects.update",
                "uploads.create", "uploads.read",
                "milestones.update", "milestones.read",
                "buyers.invite", "buyers.read",
                "members.read",
                "settings.read",
            ],
        },
        {
            "name": "developer_member",
            "description": "Developer team member - upload photos and view projects",
            "permissions": [
                "projects.read",
                "uploads.create", "uploads.read",
                "milestones.read",
                "buyers.read",
            ],
        },
        {
            "name": "buyer_viewer",
            "description": "Buyer with read-only access to their project",
            "permissions": ["projects.read", "milestones.read", "uploads.read"],
        },
    ]

    role_map = {}
    for role_data in roles_data:
        result = await db.execute(select(Role).where(Role.name == role_data["name"]))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(
                id=new_id(),
                name=role_data["name"],
                description=role_data["description"],
                is_system=True,
                created_at=now,
                updated_at=now,
            )
            db.add(role)
            await db.flush()

            for perm_name in role_data["permissions"]:
                if perm_name in perm_map:
                    result2 = await db.execute(
                        select(RolePermission).where(
                            RolePermission.role_id == role.id,
                            RolePermission.permission_id == perm_map[perm_name].id,
                        )
                    )
                    if not result2.scalar_one_or_none():
                        db.add(RolePermission(
                            id=new_id(),
                            role_id=role.id,
                            permission_id=perm_map[perm_name].id,
                            created_at=now,
                        ))
            await db.flush()
            print(f"  Created role: {role.name}")
        else:
            print(f"  Role exists: {role.name}")
        role_map[role_data["name"]] = role

    return role_map


async def seed_system_settings(db: AsyncSession):
    """Seed system-wide settings."""
    print("\n--- System Settings ---")
    now = datetime.now(timezone.utc)

    system_settings = [
        ("platform_name", "BuildTrack", "Platform display name"),
        ("max_upload_photos", "10", "Maximum photos per upload session"),
        ("min_upload_photos", "1", "Minimum photos required per upload session"),
        ("gps_accuracy_threshold_m", "100", "Maximum GPS accuracy radius in metres"),
        ("gps_site_grace_buffer_m", "20", "Grace buffer beyond project radius in metres"),
        ("trial_duration_days", "30", "Number of days in trial period"),
        ("trial_warning_days", "3", "Days before trial end to send warning email"),
        ("max_projects_trial", "1", "Max projects on trial tier"),
        ("max_projects_starter", "3", "Max projects on starter tier"),
        ("max_projects_growth", "10", "Max projects on growth tier"),
        ("max_projects_scale", "999", "Max projects on scale tier"),
    ]

    for key, value, description in system_settings:
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        if not result.scalar_one_or_none():
            db.add(SystemSetting(
                id=new_id(),
                key=key,
                value=value,
                description=description,
                updated_at=now,
                created_at=now,
            ))
            print(f"  Created system setting: {key}")
        else:
            print(f"  Setting exists: {key}")

    await db.flush()


async def seed(db: AsyncSession):
    print("Starting seed...")

    # ── Project types, workflow templates, permissions, roles ──────────────
    templates_map = await seed_project_types(db)
    role_map = await seed_permissions_and_roles(db)
    await seed_system_settings(db)

    now = datetime.now(timezone.utc)

    # ── Admin User ────────────────────────────────────────────────────────
    print("\n--- Users ---")
    admin_email = "admin@buildtrack.co.ke"
    result = await db.execute(select(User).where(User.email == admin_email))
    admin_user = result.scalar_one_or_none()
    if not admin_user:
        admin_user = User(
            id=new_id(),
            email=admin_email,
            hashed_password=hash_password("Admin@2026!"),
            role="admin",
            full_name="BuildTrack Admin",
            is_active=True,
            email_verified=True,
            created_at=now,
            updated_at=now,
        )
        db.add(admin_user)
        await db.flush()
        print(f"  Created admin: {admin_email}")
    else:
        print(f"  Admin exists: {admin_email}")

    # Assign platform_admin role to admin
    if "platform_admin" in role_map:
        result = await db.execute(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == admin_user.id,
                UserRoleAssignment.role_id == role_map["platform_admin"].id,
            )
        )
        if not result.scalar_one_or_none():
            db.add(UserRoleAssignment(
                id=new_id(),
                user_id=admin_user.id,
                role_id=role_map["platform_admin"].id,
                granted_by=admin_user.id,
                granted_at=now,
                created_at=now,
            ))
            await db.flush()

    # ── Developer User ────────────────────────────────────────────────────
    dev_email = "developer@acme.co.ke"
    result = await db.execute(select(User).where(User.email == dev_email))
    dev_user = result.scalar_one_or_none()
    if not dev_user:
        dev_user = User(
            id=new_id(),
            email=dev_email,
            hashed_password=hash_password("Developer@2026!"),
            role="developer",
            full_name="John Developer",
            is_active=True,
            email_verified=True,
            created_at=now,
            updated_at=now,
        )
        db.add(dev_user)
        await db.flush()
        print(f"  Created developer: {dev_email}")
    else:
        print(f"  Developer exists: {dev_email}")

    # ── Second developer team member ──────────────────────────────────────
    dev2_email = "site.manager@acme.co.ke"
    result = await db.execute(select(User).where(User.email == dev2_email))
    dev2_user = result.scalar_one_or_none()
    if not dev2_user:
        dev2_user = User(
            id=new_id(),
            email=dev2_email,
            hashed_password=hash_password("Manager@2026!"),
            role="developer",
            full_name="Sarah Manager",
            is_active=True,
            email_verified=True,
            created_at=now,
            updated_at=now,
        )
        db.add(dev2_user)
        await db.flush()
        print(f"  Created site manager: {dev2_email}")
    else:
        print(f"  Site manager exists: {dev2_email}")

    # ── Developer Profile ─────────────────────────────────────────────────
    result = await db.execute(select(Developer).where(Developer.user_id == dev_user.id))
    developer = result.scalar_one_or_none()
    if not developer:
        developer = Developer(
            id=new_id(),
            user_id=dev_user.id,
            company_name="Acoma Developments Ltd",
            subscription_tier="growth",
            subscription_status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(developer)
        await db.flush()
        print(f"  Created developer profile: Acoma Developments Ltd")
    else:
        print(f"  Developer profile exists")

    # ── Org Members ──────────────────────────────────────────────────────
    from app.modules.members.models import DeveloperMember
    result = await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.developer_id == developer.id,
            DeveloperMember.user_id == dev_user.id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(DeveloperMember(
            id=new_id(),
            developer_id=developer.id,
            user_id=dev_user.id,
            org_role="owner",
            invited_by=dev_user.id,
            invited_at=now,
            joined_at=now,
            is_active=True,
            created_at=now,
        ))

    result = await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.developer_id == developer.id,
            DeveloperMember.user_id == dev2_user.id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(DeveloperMember(
            id=new_id(),
            developer_id=developer.id,
            user_id=dev2_user.id,
            org_role="member",
            invited_by=dev_user.id,
            invited_at=now,
            joined_at=now,
            is_active=True,
            created_at=now,
        ))
    await db.flush()
    print(f"  Org members seeded (owner + member)")

    # Assign developer_owner role to dev_user
    if "developer_owner" in role_map:
        result = await db.execute(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == dev_user.id,
                UserRoleAssignment.role_id == role_map["developer_owner"].id,
                UserRoleAssignment.developer_id == developer.id,
            )
        )
        if not result.scalar_one_or_none():
            db.add(UserRoleAssignment(
                id=new_id(),
                user_id=dev_user.id,
                role_id=role_map["developer_owner"].id,
                developer_id=developer.id,
                granted_by=admin_user.id,
                granted_at=now,
                created_at=now,
            ))
            await db.flush()

    if "developer_member" in role_map:
        result = await db.execute(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == dev2_user.id,
                UserRoleAssignment.role_id == role_map["developer_member"].id,
                UserRoleAssignment.developer_id == developer.id,
            )
        )
        if not result.scalar_one_or_none():
            db.add(UserRoleAssignment(
                id=new_id(),
                user_id=dev2_user.id,
                role_id=role_map["developer_member"].id,
                developer_id=developer.id,
                granted_by=dev_user.id,
                granted_at=now,
                created_at=now,
            ))
            await db.flush()

    # ── Tenant Settings ───────────────────────────────────────────────────
    print("\n--- Tenant Settings ---")
    tenant_defaults = {
        "notification_on_upload_approved": "true",
        "notification_on_milestone_complete": "true",
        "notification_on_milestone_delayed": "true",
        "buyer_can_comment": "false",
        "upload_require_caption": "true",
        "upload_min_photos": "1",
        "upload_max_photos": "10",
    }
    for key, value in tenant_defaults.items():
        result = await db.execute(
            select(TenantSetting).where(TenantSetting.developer_id == developer.id, TenantSetting.key == key)
        )
        if not result.scalar_one_or_none():
            db.add(TenantSetting(
                id=new_id(),
                developer_id=developer.id,
                key=key,
                value=value,
                updated_at=now,
                created_at=now,
            ))
    await db.flush()
    print(f"  Seeded {len(tenant_defaults)} tenant settings")

    # ── Project ───────────────────────────────────────────────────────────
    print("\n--- Project ---")
    project_code = "SYCA01"
    result = await db.execute(select(Project).where(Project.project_code == project_code))
    project = result.scalar_one_or_none()

    off_plan_apt_template, apt_stages = templates_map.get("Off-Plan Apartment", (None, []))

    if not project:
        project = Project(
            id=new_id(),
            developer_id=developer.id,
            project_code=project_code,
            name="Sycamore Residences",
            description="Luxury residential development in Kilimani with 48 units",
            location_name="Kilimani, Nairobi",
            site_latitude=-1.2921,
            site_longitude=36.8219,
            gps_radius_metres=150.0,
            total_units=48,
            status="construction",
            is_public=True,
            estimated_completion=datetime(2027, 6, 30, tzinfo=timezone.utc),
            project_type_id=off_plan_apt_template.project_type_id if off_plan_apt_template else None,
            workflow_template_id=off_plan_apt_template.id if off_plan_apt_template else None,
            created_at=now,
            updated_at=now,
        )
        db.add(project)
        await db.flush()
        print(f"  Created project: {project.name} ({project_code})")
    else:
        # Backfill workflow template on existing project
        if off_plan_apt_template and not project.workflow_template_id:
            project.workflow_template_id = off_plan_apt_template.id
            project.project_type_id = off_plan_apt_template.project_type_id
            await db.flush()
        print(f"  Project exists: {project_code}")

    # ── Milestones ────────────────────────────────────────────────────────
    print("\n--- Milestones ---")
    result = await db.execute(select(Milestone).where(Milestone.project_id == project.id))
    existing_milestones = result.scalars().all()

    if not existing_milestones:
        stage_map = {s.name: s for s in apt_stages} if apt_stages else {}
        milestones_data = [
            {
                "name": "Pre-Construction",
                "order_index": 1,
                "status": "complete",
                "expected_date": datetime(2026, 1, 31, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
            },
            {
                "name": "Foundation",
                "order_index": 2,
                "status": "complete",
                "expected_date": datetime(2026, 3, 31, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 4, 5, tzinfo=timezone.utc),
            },
            {
                "name": "Superstructure",
                "order_index": 3,
                "status": "in_progress",
                "expected_date": datetime(2026, 8, 31, tzinfo=timezone.utc),
            },
            {
                "name": "Building Envelope",
                "order_index": 4,
                "status": "pending",
                "expected_date": datetime(2026, 12, 31, tzinfo=timezone.utc),
            },
            {
                "name": "Practical Completion",
                "order_index": 5,
                "status": "pending",
                "expected_date": datetime(2027, 6, 30, tzinfo=timezone.utc),
            },
        ]

        for m in milestones_data:
            stage = stage_map.get(m["name"])
            milestone = Milestone(
                id=new_id(),
                project_id=project.id,
                workflow_stage_id=stage.id if stage else None,
                created_at=now,
                updated_at=now,
                **m,
            )
            db.add(milestone)
        await db.flush()
        print(f"  Created 5 milestones")
    else:
        # Backfill workflow_stage_id on existing milestones
        if apt_stages:
            stage_map = {s.name: s for s in apt_stages}
            for m in existing_milestones:
                if not m.workflow_stage_id and m.name in stage_map:
                    m.workflow_stage_id = stage_map[m.name].id
            await db.flush()
        print(f"  Milestones exist ({len(existing_milestones)})")

    # ── Buyers ────────────────────────────────────────────────────────────
    print("\n--- Buyers ---")
    buyers_to_create = [
        {"email": "buyer1@test.com", "full_name": "Alice Buyer", "unit_number": "A101"},
        {"email": "buyer2@test.com", "full_name": "Bob Buyer", "unit_number": "B205"},
    ]

    for buyer_data in buyers_to_create:
        result = await db.execute(
            select(Buyer).where(Buyer.email == buyer_data["email"], Buyer.project_id == project.id)
        )
        if not result.scalar_one_or_none():
            result2 = await db.execute(select(User).where(User.email == buyer_data["email"]))
            buyer_user = result2.scalar_one_or_none()
            if not buyer_user:
                buyer_user = User(
                    id=new_id(),
                    email=buyer_data["email"],
                    hashed_password=hash_password("Buyer@2026!"),
                    role="buyer",
                    full_name=buyer_data["full_name"],
                    is_active=True,
                    email_verified=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(buyer_user)
                await db.flush()

            # Assign buyer_viewer role
            if "buyer_viewer" in role_map:
                result3 = await db.execute(
                    select(UserRoleAssignment).where(
                        UserRoleAssignment.user_id == buyer_user.id,
                        UserRoleAssignment.role_id == role_map["buyer_viewer"].id,
                    )
                )
                if not result3.scalar_one_or_none():
                    db.add(UserRoleAssignment(
                        id=new_id(),
                        user_id=buyer_user.id,
                        role_id=role_map["buyer_viewer"].id,
                        granted_by=admin_user.id,
                        granted_at=now,
                        created_at=now,
                    ))

            buyer = Buyer(
                id=new_id(),
                user_id=buyer_user.id,
                project_id=project.id,
                email=buyer_data["email"],
                full_name=buyer_data["full_name"],
                unit_number=buyer_data["unit_number"],
                invitation_sent_at=now,
                registered_at=now,
                notification_email=True,
                created_at=now,
                updated_at=now,
            )
            db.add(buyer)
            await db.flush()
            print(f"  Created buyer: {buyer_data['email']}")
        else:
            print(f"  Buyer exists: {buyer_data['email']}")

    # ── Test Upload ───────────────────────────────────────────────────────
    print("\n--- Test Upload ---")
    idem_key = "seed_upload_001"
    result = await db.execute(select(Upload).where(Upload.idempotency_key == idem_key))
    if not result.scalar_one_or_none():
        upload = Upload(
            id=new_id(),
            project_id=project.id,
            developer_id=developer.id,
            idempotency_key=idem_key,
            caption="Foundation work in progress - concrete pour",
            capture_latitude=-1.2921,
            capture_longitude=36.8219,
            accuracy_m=8.5,
            gps_validated=True,
            photo_count=2,
            status="approved",
            notification_fanout_status="complete",
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        db.add(upload)
        await db.flush()

        for i, public_id in enumerate([
            "buildtrack/dev/projects/seed/foundation_01",
            "buildtrack/dev/projects/seed/foundation_02",
        ]):
            photo = Photo(
                id=new_id(),
                upload_id=upload.id,
                cloudinary_public_id=public_id,
                cloudinary_url=f"https://res.cloudinary.com/demo/image/upload/{public_id}",
                original_filename=f"foundation_photo_{i+1}.jpg",
                capture_latitude=-1.2921,
                capture_longitude=36.8219,
                accuracy_m=8.5,
                order_index=i,
                created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            )
            db.add(photo)
        print(f"  Created test upload with 2 photos")
    else:
        print(f"  Upload exists")

    await db.commit()

    print("\n" + "=" * 50)
    print("Seed complete!")
    print("=" * 50)
    print(f"  Admin:         admin@buildtrack.co.ke / Admin@2026!")
    print(f"  Developer:     developer@acme.co.ke  / Developer@2026!")
    print(f"  Site Manager:  site.manager@acme.co.ke / Manager@2026!")
    print(f"  Buyers:        buyer1@test.com, buyer2@test.com / Buyer@2026!")
    print(f"  Project code:  SYCA01")
    print(f"  Workflow templates: {len(templates_map)}")
    print(f"  System roles: {len(role_map)}")


async def main():
    async with async_session_factory() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
