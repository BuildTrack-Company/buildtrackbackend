"""
Seed the BuildTrack database with the Belgravia Place demo project
(developer Hanz Group Kenya) as requested by Alex for the pitch pipeline.

Reuses the shared "Off-Plans" project type / workflow template (the same
8-stage template already in use on Summer's live Butterfly Palace account)
so milestone names line up with real platform stages, and reuses the local
seed image pool + Cloudinary upload helper from seed_client.py.

Run: backend/.venv/bin/python scripts/seed_belgravia.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.core.database import async_session_factory
from app.core.security import hash_password
from app.shared.ids import new_id

from app.modules.auth.models import User
from app.modules.developers.models import Developer
from app.modules.projects.models import Project
from app.modules.milestones.models import Milestone
from app.modules.uploads.models import Upload
from app.modules.members.models import DeveloperMember
from app.modules.roles.models import UserRoleAssignment, Role

from scripts.seed_client import upload_images, delivery_url, add_photos

PROJECT_TYPE_ID = "019f4685-6a5e-7df4-b632-ef1e22111ae3"
WORKFLOW_TEMPLATE_ID = "019f5fec-4f37-7353-93d5-d39adffef6eb"

STAGE_IDS = {
    "Site Preparation": "019f5fec-4faf-75ee-ae0c-16147f54c3a2",
    "Excavation and Foundation": "019f5fec-5028-7d7f-9ca5-adc75dc59d6e",
    "Superstructure (Columns, Beams & Slabs)": "019f5fec-5063-7713-a942-bd4342fcecb5",
    "External Walling": "019f5fec-509e-7a7c-8804-13359b1f8f87",
    "Windows and Doors Installation": "019f5fec-50d9-74a7-a524-7017bd05692d",
    "External Plastering and Painting": "019f5fec-5114-79f7-83f8-fcc1ee72bdd4",
    "Interior Finishes": "019f5fec-5150-74f6-b1ae-3075b7c7f16c",
    "Landscaping and External Works": "019f5fec-518b-7386-a999-5f0c2a7bf056",
}


def D(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


DEV = dict(
    email="hanzgroup@buildtrack.co.ke", password="Hanz@2026!",
    company="Hanz Group Kenya", years=6, completed=2, active=1,
    freq_days=14.0,
    overview=(
        "Hanz Group Kenya is a Nairobi-based residential developer with 6 years in the "
        "market and 2 completed projects. The company focuses on delivering well-located, "
        "high-rise residential developments, with an emphasis on transparent buyer "
        "communication throughout the construction process, particularly for clients "
        "unable to visit the site regularly."
    ),
)

PROJECT = dict(
    code="BELG01", slug="belgravia-place", name="Belgravia Place",
    location="Vihiga Road, Kileleshwa, Nairobi", lat=-1.293515, lng=36.835321,
    units=264, completion=D(2029, 12, 31),
    tagline="A thoughtful way to live.",
    description=(
        "Belgravia Place is a 264-unit residential tower located along Vihiga Road in "
        "Kileleshwa, Nairobi. Rising 24 floors, the development is currently in its early "
        "construction stages. Construction updates for this project are captured on-site, "
        "GPS-verified at the point of upload, and reviewed before publication, giving "
        "buyers an independently verifiable record of progress from foundation through "
        "handover. Updates are shared every 14 days in line with the developer's "
        "commitment to consistent, transparent reporting, with particular attention to "
        "buyers who are unable to visit the site in person."
    ),
)

MILESTONES = [
    # (name, status, expected_date, completed_at)
    ("Site Preparation", "complete", D(2026, 5, 31), D(2026, 6, 12)),
    ("Excavation and Foundation", "in_progress", D(2026, 11, 30), None),
    ("Superstructure (Columns, Beams & Slabs)", "pending", D(2028, 2, 29), None),
    ("External Walling", "pending", D(2028, 7, 31), None),
    ("Windows and Doors Installation", "pending", D(2028, 10, 31), None),
    ("External Plastering and Painting", "pending", D(2029, 2, 28), None),
    ("Interior Finishes", "pending", D(2029, 8, 31), None),
    ("Landscaping and External Works", "pending", D(2029, 12, 31), None),
]

# (title, category, date, progress_pct, milestone_order, description)
UPDATES = [
    ("Site Clearance & Perimeter Fencing Complete", "Site Preparation", D(2026, 5, 10), 5, 1,
     "Site clearance and grading works completed across the full project footprint. "
     "Perimeter hoarding and site fencing installed to secure the plot ahead of "
     "excavation. Site office and welfare facilities for the construction team "
     "established on-site."),
    ("Site Survey & Soil Testing Confirmed", "Site Preparation", D(2026, 5, 28), 7, 1,
     "Detailed site survey and soil testing completed to confirm ground conditions "
     "ahead of excavation and foundation design. Results confirmed suitable for the "
     "planned 24-floor structure."),
    ("Site Mobilization Complete", "Site Preparation", D(2026, 6, 12), 9, 1,
     "Construction equipment, machinery, and materials mobilized to site. Access roads "
     "within the site established to support excavation and future construction "
     "traffic."),
    ("Excavation Works Commenced", "Excavation and Foundation", D(2026, 6, 29), 12, 2,
     "Excavation works officially commenced across the building footprint, marking the "
     "start of the foundation phase. Excavation is proceeding in line with the approved "
     "structural plan."),
    ("Excavation Progressing to Required Depth", "Excavation and Foundation", D(2026, 7, 20), 16, 2,
     "Excavation works continuing steadily, with the team progressing toward the "
     "required depth across the building footprint ahead of foundation casting. Ground "
     "conditions remain stable and consistent with earlier soil testing."),
    ("Excavation Nearing Completion", "Excavation and Foundation", D(2026, 7, 23), 18, 2,
     "Excavation works are nearing completion across the site, with the team on track "
     "to begin foundation shuttering and reinforcement works shortly. This marks steady "
     "progress toward the conclusion of the excavation stage."),
]


async def main():
    print("Uploading images to Cloudinary...")
    IMG = upload_images()
    print(f"  {len(IMG)} images ready")

    # site-prep / early-earthworks image pool vs excavation/structural pool
    PREP = [IMG[1], IMG[3], IMG[4], IMG[7]]
    EXCAV = [IMG[0], IMG[5], IMG[6], IMG[2]]

    async with async_session_factory() as db:
        now = datetime.now(timezone.utc)

        admin = (await db.execute(select(User).where(User.email == "admin@buildtrack.co.ke"))).scalar_one_or_none()
        admin_id = admin.id if admin else None

        user = (await db.execute(select(User).where(User.email == DEV["email"]))).scalar_one_or_none()
        if not user:
            user = User(
                id=new_id(), email=DEV["email"], hashed_password=hash_password(DEV["password"]),
                role="developer", full_name=DEV["company"], is_active=True, email_verified=True,
                created_at=now, updated_at=now,
            )
            db.add(user)
            await db.flush()

        developer = (await db.execute(select(Developer).where(Developer.user_id == user.id))).scalar_one_or_none()
        if not developer:
            developer = Developer(id=new_id(), user_id=user.id)
            db.add(developer)
        developer.company_name = DEV["company"]
        developer.years_operating = DEV["years"]
        developer.projects_completed = DEV["completed"]
        developer.active_developments = DEV["active"]
        developer.avg_update_frequency_days = DEV["freq_days"]
        developer.company_overview = DEV["overview"]
        developer.subscription_tier = "trial"
        developer.subscription_status = "active"
        developer.updated_at = now
        await db.flush()

        if not (await db.execute(select(DeveloperMember).where(
            DeveloperMember.developer_id == developer.id, DeveloperMember.user_id == user.id
        ))).scalar_one_or_none():
            db.add(DeveloperMember(
                id=new_id(), developer_id=developer.id, user_id=user.id, org_role="owner",
                invited_by=user.id, invited_at=now, joined_at=now, is_active=True, created_at=now,
            ))
        owner_role = (await db.execute(select(Role).where(Role.name == "developer_owner"))).scalar_one_or_none()
        if owner_role and not (await db.execute(select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user.id, UserRoleAssignment.role_id == owner_role.id,
            UserRoleAssignment.developer_id == developer.id,
        ))).scalar_one_or_none():
            db.add(UserRoleAssignment(
                id=new_id(), user_id=user.id, role_id=owner_role.id, developer_id=developer.id,
                granted_by=admin_id or user.id, granted_at=now, created_at=now,
            ))

        project = (await db.execute(select(Project).where(Project.project_code == PROJECT["code"]))).scalar_one_or_none()
        if not project:
            project = Project(id=new_id(), developer_id=developer.id, project_code=PROJECT["code"])
            db.add(project)
        project.developer_id = developer.id
        project.slug = PROJECT["slug"]
        project.name = PROJECT["name"]
        project.description = PROJECT["description"]
        project.location_name = PROJECT["location"]
        project.site_latitude = PROJECT["lat"]
        project.site_longitude = PROJECT["lng"]
        project.gps_radius_metres = 100.0
        project.total_units = PROJECT["units"]
        project.status = "active"
        project.estimated_completion = PROJECT["completion"]
        project.is_public = True
        project.visibility_description = PROJECT["description"]
        project.visibility_tagline = PROJECT["tagline"]
        project.construction_progress = UPDATES[-1][3]
        project.health_status = "on_schedule"
        project.activity_overdue_threshold_days = 14
        project.visibility_page_published = True
        project.project_type_id = PROJECT_TYPE_ID
        project.workflow_template_id = WORKFLOW_TEMPLATE_ID
        project.current_stage_id = STAGE_IDS["Excavation and Foundation"]
        project.cover_image_url = delivery_url(EXCAV[-1])
        project.updated_at = now
        await db.flush()

        ms_by_name = {m.name: m for m in (await db.execute(
            select(Milestone).where(Milestone.project_id == project.id)
        )).scalars().all()}
        for order, (mname, status, exp, done) in enumerate(MILESTONES, start=1):
            m = ms_by_name.get(mname)
            if not m:
                m = Milestone(id=new_id(), project_id=project.id, name=mname, created_at=now)
                db.add(m)
            m.order_index = order
            m.status = status
            m.expected_date = exp
            m.completed_at = done
            m.workflow_stage_id = STAGE_IDS.get(mname)
            m.updated_at = now
            ms_by_name[mname] = m
        await db.flush()

        mnames = [m[0] for m in MILESTONES]
        for n, (title, cat, when, prog, ms_order, desc) in enumerate(UPDATES, start=1):
            idem = f"seed_{PROJECT['code']}_u{n}"
            existing = (await db.execute(select(Upload).where(Upload.idempotency_key == idem))).scalar_one_or_none()
            if existing:
                continue
            milestone = ms_by_name.get(mnames[ms_order - 1])
            imgs = (PREP if ms_order == 1 else EXCAV)[(n - 1) % 2 * 2: (n - 1) % 2 * 2 + 2] or PREP[:2]
            up = Upload(
                id=new_id(), project_id=project.id, developer_id=developer.id,
                milestone_id=milestone.id if milestone else None, idempotency_key=idem,
                title=title, category=cat, caption=desc, progress_at_upload=prog,
                capture_latitude=PROJECT["lat"], capture_longitude=PROJECT["lng"],
                accuracy_m=8.0, distance_from_site_m=10.0, within_boundary=True,
                gps_validated=True, photo_count=2, status="approved",
                reviewed_at=when, reviewed_by=admin_id,
                notification_fanout_status="complete", notification_fanout_at=when,
                created_at=when, updated_at=when,
            )
            db.add(up)
            await db.flush()
            await add_photos(db, up, imgs, PROJECT["lat"], PROJECT["lng"], when)

        await db.commit()
    print("\nSeed complete. Developer login: hanzgroup@buildtrack.co.ke / Hanz@2026!")
    print(f"Project code: {PROJECT['code']}  slug: /{PROJECT['slug']}")


if __name__ == "__main__":
    asyncio.run(main())
