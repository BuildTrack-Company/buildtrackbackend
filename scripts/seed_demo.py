"""
Rich demo seed for BuildTrack v2.

Layers realistic demo data on top of the base seed (scripts/seed_dev.py):
  - 3 developer companies with credibility profiles
  - 8 projects across 5 areas and all project types, varied stages
  - 30+ buyers (local + diaspora)
  - 40+ construction updates (uploads) with real Cloudinary photos
  - 15 inquiries, 200+ visibility page views
  - notification log + audit log history

Real photos are uploaded ONCE from scripts/seed_images/ and reused by
public_id across all uploads, so the gallery shows real images.

Run:  .venv/Scripts/python scripts/seed_demo.py
Idempotent: safe to re-run (entities are get-or-created; bulk rows are guarded).
"""
import asyncio
import os
import sys
import random
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.security import hash_password
from app.shared.ids import new_id
from app.shared import storage  # configures cloudinary on import
import cloudinary.uploader

from app.modules.auth.models import User
from app.modules.developers.models import Developer
from app.modules.members.models import DeveloperMember
from app.modules.projects.models import Project
from app.modules.milestones.models import Milestone
from app.modules.buyers.models import Buyer
from app.modules.uploads.models import Upload, Photo
from app.modules.inquiries.models import Inquiry, VisibilityPageView
from app.modules.notifications.models import NotificationLog
from app.modules.project_types.models import WorkflowTemplate, WorkflowStage
from app.modules.roles.models import Role, UserRoleAssignment

from scripts.seed_dev import seed as base_seed

SEED_IMAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_images")
IMAGE_NAMES = ["foundation", "superstructure", "roof", "envelope", "finishes", "site", "exterior", "interior"]

CATEGORIES = [
    "Foundation Works", "Structural Works", "Roofing Works", "Facade Works",
    "MEP Installation", "Finishing Works", "Milestone Completed", "General Update",
]
COUNTRIES = ["KE", "KE", "KE", "GB", "CA", "AE", "US", "ZA", "RW", "UG", "TZ", "AU"]
DEFAULT_PASSWORD = "Buyer@2026!"


# ──────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────
async def upload_seed_images() -> dict:
    """Upload the 8 seed images to Cloudinary once; return {name: (public_id, url)}."""
    out = {}
    for name in IMAGE_NAMES:
        path = os.path.join(SEED_IMAGES, f"{name}.jpg")
        if not os.path.exists(path):
            print(f"  WARNING: missing seed image {path}")
            continue
        public_id = f"{storage.settings.CLOUDINARY_FOLDER_ROOT}/seed/{name}"
        try:
            res = await asyncio.to_thread(
                cloudinary.uploader.upload, path,
                public_id=public_id, overwrite=True, resource_type="image",
            )
            out[name] = (res["public_id"], res.get("secure_url"))
        except Exception as e:
            # Fall back to a deterministic public_id/url so seeding still completes.
            print(f"  WARNING: cloudinary upload failed for {name}: {e}")
            out[name] = (public_id, f"https://res.cloudinary.com/{storage.settings.CLOUDINARY_CLOUD_NAME}/image/upload/{public_id}.jpg")
    print(f"  Uploaded/resolved {len(out)} seed images to Cloudinary")
    return out


async def get_or_create_user(db, email, full_name, role, password=DEFAULT_PASSWORD, now=None):
    now = now or datetime.now(timezone.utc)
    res = await db.execute(select(User).where(User.email == email))
    u = res.scalar_one_or_none()
    if u:
        return u, False
    u = User(
        id=new_id(), email=email, hashed_password=hash_password(password),
        role=role, full_name=full_name, is_active=True, email_verified=True,
        created_at=now, updated_at=now,
    )
    db.add(u)
    await db.flush()
    return u, True


async def assign_role(db, user_id, role_id, developer_id, granted_by, now):
    res = await db.execute(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.role_id == role_id,
        )
    )
    if res.scalar_one_or_none():
        return
    db.add(UserRoleAssignment(
        id=new_id(), user_id=user_id, role_id=role_id, developer_id=developer_id,
        granted_by=granted_by, granted_at=now, created_at=now,
    ))


async def get_or_create_developer(db, *, email, contact_name, company_name, tier, profile, role_map, admin_id, now):
    user, _ = await get_or_create_user(db, email, contact_name, "developer", "Developer@2026!", now)
    res = await db.execute(select(Developer).where(Developer.user_id == user.id))
    dev = res.scalar_one_or_none()
    if not dev:
        dev = Developer(
            id=new_id(), user_id=user.id, company_name=company_name,
            contact_name=contact_name, subscription_tier=tier, subscription_status="active",
            created_at=now, updated_at=now, **profile,
        )
        db.add(dev)
        await db.flush()
    else:
        # keep credibility profile + tier current
        dev.contact_name = contact_name
        dev.subscription_tier = tier
        for k, v in profile.items():
            setattr(dev, k, v)
        await db.flush()

    # org membership (owner)
    res = await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.developer_id == dev.id, DeveloperMember.user_id == user.id
        )
    )
    if not res.scalar_one_or_none():
        db.add(DeveloperMember(
            id=new_id(), developer_id=dev.id, user_id=user.id, org_role="owner",
            invited_by=user.id, invited_at=now, joined_at=now, is_active=True, created_at=now,
        ))
    if "developer_owner" in role_map:
        await assign_role(db, user.id, role_map["developer_owner"].id, dev.id, admin_id, now)
    await db.flush()
    return dev, user


async def load_templates(db) -> dict:
    """Return {template_name: (template, [stages ordered])}."""
    out = {}
    res = await db.execute(select(WorkflowTemplate))
    for tpl in res.scalars().all():
        sres = await db.execute(
            select(WorkflowStage).where(WorkflowStage.workflow_template_id == tpl.id).order_by(WorkflowStage.order_index)
        )
        out[tpl.name] = (tpl, list(sres.scalars().all()))
    return out


async def create_milestones(db, project, stages, progress, now):
    """Create 5 milestones from the template stages, completion driven by progress%."""
    res = await db.execute(select(func.count()).select_from(Milestone).where(Milestone.project_id == project.id))
    if res.scalar_one() > 0:
        return
    n = len(stages) or 5
    completed = max(0, min(n, round(progress / 100 * n)))
    base_date = now - timedelta(days=180)
    for i, stage in enumerate(stages or []):
        if i < completed:
            status = "complete"
            completed_at = base_date + timedelta(days=30 * (i + 1))
            expected = completed_at - timedelta(days=3)
        elif i == completed:
            status = "in_progress"
            completed_at = None
            expected = now + timedelta(days=45)
        else:
            status = "pending"
            completed_at = None
            expected = now + timedelta(days=90 * (i - completed + 1))
        db.add(Milestone(
            id=new_id(), project_id=project.id, name=stage.name, order_index=stage.order_index,
            status=status, expected_date=expected, completed_at=completed_at,
            workflow_stage_id=stage.id, created_at=now, updated_at=now,
        ))
    await db.flush()


async def first_milestone(db, project_id):
    res = await db.execute(
        select(Milestone).where(Milestone.project_id == project_id).order_by(Milestone.order_index)
    )
    return list(res.scalars().all())


async def create_uploads_for_project(db, project, dev_id, images, count, latest_days_ago, now,
                                      pending=0, flagged=0):
    """Create `count` approved uploads staggered over 6 months, plus pending/flagged extras."""
    res = await db.execute(select(func.count()).select_from(Upload).where(Upload.project_id == project.id))
    existing = res.scalar_one()
    if existing >= count:
        return 0
    milestones = await first_milestone(db, project.id)
    img_keys = list(images.keys())
    created = 0
    # approved series, oldest -> newest, newest is `latest_days_ago` old
    span_days = 175
    for i in range(count):
        frac = (i + 1) / count
        days_ago = int(latest_days_ago + (span_days - latest_days_ago) * (1 - frac))
        created_at = now - timedelta(days=days_ago, hours=random.randint(0, 12))
        progress = max(2, min(project.construction_progress, int(project.construction_progress * frac)))
        idem = f"seed-{project.project_code}-{i}"
        r = await db.execute(select(Upload).where(Upload.idempotency_key == idem))
        if r.scalar_one_or_none():
            continue
        cat = CATEGORIES[i % len(CATEGORIES)]
        ms = milestones[min(len(milestones) - 1, int(frac * max(0, len(milestones) - 1)))] if milestones else None
        up = Upload(
            id=new_id(), project_id=project.id, developer_id=dev_id,
            milestone_id=ms.id if ms else None, idempotency_key=idem,
            title=f"{cat} update {i + 1}", caption=f"{cat} progress recorded on site.",
            category=cat, progress_at_upload=progress,
            capture_latitude=(project.site_latitude or -1.29) + random.uniform(-0.0003, 0.0003),
            capture_longitude=(project.site_longitude or 36.82) + random.uniform(-0.0003, 0.0003),
            accuracy_m=round(random.uniform(4, 12), 1),
            distance_from_site_m=round(random.uniform(5, 60), 1), within_boundary=True,
            gps_validated=True, photo_count=random.randint(2, 4), status="approved",
            notification_fanout_status="complete", notification_fanout_at=created_at,
            reviewed_at=created_at, created_at=created_at, updated_at=created_at,
        )
        db.add(up)
        await db.flush()
        for j in range(up.photo_count):
            key = img_keys[(i + j) % len(img_keys)]
            pid, url = images[key]
            db.add(Photo(
                id=new_id(), upload_id=up.id, cloudinary_public_id=pid, cloudinary_url=url,
                original_filename=f"{key}.jpg",
                capture_latitude=up.capture_latitude, capture_longitude=up.capture_longitude,
                accuracy_m=up.accuracy_m, order_index=j, created_at=created_at,
            ))
        created += 1

    # pending (review queue)
    for p in range(pending):
        idem = f"seed-{project.project_code}-pending-{p}"
        r = await db.execute(select(Upload).where(Upload.idempotency_key == idem))
        if r.scalar_one_or_none():
            continue
        created_at = now - timedelta(days=random.randint(0, 3))
        up = Upload(
            id=new_id(), project_id=project.id, developer_id=dev_id, idempotency_key=idem,
            title="Awaiting review", caption="Recent site update pending admin review.",
            category="General Update", progress_at_upload=project.construction_progress,
            capture_latitude=project.site_latitude, capture_longitude=project.site_longitude,
            accuracy_m=7.0, distance_from_site_m=18.0, within_boundary=True, gps_validated=True,
            photo_count=2, status="pending", notification_fanout_status="pending",
            created_at=created_at, updated_at=created_at,
        )
        db.add(up)
        await db.flush()
        for j in range(2):
            key = img_keys[j % len(img_keys)]
            pid, url = images[key]
            db.add(Photo(id=new_id(), upload_id=up.id, cloudinary_public_id=pid, cloudinary_url=url,
                         original_filename=f"{key}.jpg", capture_latitude=up.capture_latitude,
                         capture_longitude=up.capture_longitude, accuracy_m=7.0, order_index=j, created_at=created_at))
        created += 1

    # flagged (rejected)
    for f in range(flagged):
        idem = f"seed-{project.project_code}-flagged-{f}"
        r = await db.execute(select(Upload).where(Upload.idempotency_key == idem))
        if r.scalar_one_or_none():
            continue
        created_at = now - timedelta(days=random.randint(5, 20))
        up = Upload(
            id=new_id(), project_id=project.id, developer_id=dev_id, idempotency_key=idem,
            title="Rejected update", caption="Photo quality insufficient.",
            category="General Update", progress_at_upload=project.construction_progress,
            capture_latitude=project.site_latitude, capture_longitude=project.site_longitude,
            accuracy_m=9.0, distance_from_site_m=22.0, within_boundary=True, gps_validated=True,
            photo_count=1, status="flagged", flag_reason="Image too blurry to verify progress.",
            reviewed_at=created_at, created_at=created_at, updated_at=created_at,
        )
        db.add(up)
        await db.flush()
        key = img_keys[0]
        pid, url = images[key]
        db.add(Photo(id=new_id(), upload_id=up.id, cloudinary_public_id=pid, cloudinary_url=url,
                     original_filename=f"{key}.jpg", capture_latitude=up.capture_latitude,
                     capture_longitude=up.capture_longitude, accuracy_m=9.0, order_index=0, created_at=created_at))
        created += 1
    await db.flush()
    return created


async def create_buyer(db, project, email, full_name, unit, role_map, admin_id, now,
                       phone=None, registered=True):
    res = await db.execute(select(Buyer).where(Buyer.email == email, Buyer.project_id == project.id))
    if res.scalar_one_or_none():
        return
    user, _ = await get_or_create_user(db, email, full_name, "buyer", DEFAULT_PASSWORD, now)
    if "buyer_viewer" in role_map:
        await assign_role(db, user.id, role_map["buyer_viewer"].id, None, admin_id, now)
    db.add(Buyer(
        id=new_id(), user_id=user.id if registered else None, project_id=project.id,
        email=email, full_name=full_name, unit_number=unit, phone=phone,
        invitation_sent_at=now - timedelta(days=40),
        registered_at=now - timedelta(days=random.randint(1, 35)) if registered else None,
        notification_email=True, notification_whatsapp=random.random() < 0.4,
        created_at=now, updated_at=now,
    ))
    await db.flush()


# ──────────────────────────────────────────────────────────────────────────
# main seed
# ──────────────────────────────────────────────────────────────────────────
async def seed_demo(db: AsyncSession):
    random.seed(42)
    now = datetime.now(timezone.utc)

    print("\n=== Running base seed first (roles, types, admin, Acoma) ===")
    await base_seed(db)

    # role + template lookup
    role_res = await db.execute(select(Role))
    role_map = {r.name: r for r in role_res.scalars().all()}
    templates = await load_templates(db)
    admin = (await db.execute(select(User).where(User.email == "admin@buildtrack.co.ke"))).scalar_one()

    print("\n=== Cloudinary seed images ===")
    images = await upload_seed_images()
    if not images:
        print("  No images available; aborting demo seed."); return

    # ── Developers ──────────────────────────────────────────────────────────
    print("\n=== Developers ===")
    acoma = (await db.execute(
        select(Developer).where(Developer.company_name == "Acoma Developments Ltd")
    )).scalar_one_or_none()
    if acoma:
        acoma.contact_name = "Daniel Acoma"
        acoma.years_operating = 5
        acoma.projects_completed = 8
        acoma.active_developments = 3
        acoma.avg_update_frequency_days = 6.2
        acoma.update_consistency_pct = 92.0
        acoma.company_overview = ("Acoma Developments delivers mid-market residential developments "
                                  "across Nairobi with a focus on transparent, verified construction reporting.")
        acoma.subscription_tier = "medium"
        await db.flush()
        acoma_owner = (await db.execute(select(User).where(User.id == acoma.user_id))).scalar_one()
        print("  Updated Acoma Developments profile")

    skyline, _ = await get_or_create_developer(
        db, email="owner@skyline.co.ke", contact_name="Grace Skyline",
        company_name="Skyline Properties Kenya", tier="enterprise",
        profile=dict(years_operating=12, projects_completed=23, active_developments=4,
                     avg_update_frequency_days=4.8, update_consistency_pct=88.0,
                     company_overview="Skyline Properties Kenya is an established developer with over a decade "
                                      "delivering premium residential and mixed-use developments."),
        role_map=role_map, admin_id=admin.id, now=now)
    print("  Skyline Properties Kenya ready")

    greenline, _ = await get_or_create_developer(
        db, email="owner@greenline.co.ke", contact_name="Peter Greenline",
        company_name="Greenline Homes", tier="small",
        profile=dict(years_operating=3, projects_completed=4, active_developments=2,
                     avg_update_frequency_days=5.5, update_consistency_pct=95.0,
                     company_overview="Greenline Homes is a fast-growing developer building boutique, "
                                      "high-quality homes with industry-leading update consistency."),
        role_map=role_map, admin_id=admin.id, now=now)
    print("  Greenline Homes ready")

    apt = templates.get("Off-Plan Apartment")
    villa = templates.get("Off-Plan Villa/Townhouse")
    commercial = templates.get("Commercial Building")

    # ── Projects ──────────────────────────────────────────────────────────
    print("\n=== Projects ===")
    # (dev, code, name, slug, area, lat, lng, units, tpl, progress, health, published, latest_days_ago, pending, flagged)
    specs = [
        (acoma, "HIGH01", "Highpoint 336", "highpoint-336-kilimani", "Kilimani, Nairobi", -1.2895, 36.7820, 72, apt, 88, "on_schedule", True, 2, 1, 0),
        (acoma, "AMTH01", "Amethyst Court", "amethyst-court-kileleshwa", "Kileleshwa, Nairobi", -1.2860, 36.7790, 96, apt, 70, "minor_delay", True, 30, 0, 1),
        (skyline, "BERK01", "Berkeley Place", "berkeley-place-westlands", "Westlands, Nairobi", -1.2670, 36.8060, 280, commercial, 30, "on_schedule", True, 3, 1, 0),
        (skyline, "KARN01", "Karen Ridge Villas", "karen-ridge-villas", "Karen, Nairobi", -1.3190, 36.7060, 24, villa, 92, "on_schedule", True, 1, 0, 0),
        (skyline, "LAVN01", "The Lavington Collection", "lavington-collection", "Lavington, Nairobi", -1.2790, 36.7660, 36, villa, 50, "minor_delay", False, 4, 0, 1),
        (greenline, "WSTV01", "Westlands Boutique Villas", "westlands-boutique-villas", "Westlands, Nairobi", -1.2655, 36.8030, 12, villa, 75, "under_review", True, 5, 1, 0),
        (greenline, "RVBK01", "Riverbank Apartments", "riverbank-apartments-kilimani", "Kilimani, Nairobi", -1.2910, 36.7855, 60, apt, 10, "on_schedule", False, 6, 0, 0),
    ]

    projects = []
    # include Acoma's existing Sycamore as the 8th, enrich it
    sycamore = (await db.execute(select(Project).where(Project.project_code == "SYCA01"))).scalar_one_or_none()
    if sycamore:
        sycamore.slug = sycamore.slug or "sycamore-residences-kilimani"
        sycamore.construction_progress = 55
        sycamore.health_status = "on_schedule"
        sycamore.visibility_page_published = True
        sycamore.visibility_tagline = "Verified progress on a 48-unit Kilimani development."
        sycamore.visibility_description = ("Sycamore Residences is a luxury 48-unit development in Kilimani. "
                                           "Every construction update is GPS-verified on site and admin-reviewed before publishing.")
        sycamore.starting_price = "KES 9.5M"
        sycamore.activity_overdue_threshold_days = 14
        await db.flush()
        projects.append((sycamore, acoma, 6, 2, 0, 0))
        print("  Enriched Sycamore Residences")

    for (dev, code, name, slug, area, lat, lng, units, tpl, progress, health, published, latest, pending, flagged) in specs:
        existing = (await db.execute(select(Project).where(Project.project_code == code))).scalar_one_or_none()
        tpl_obj, tpl_stages = tpl if tpl else (None, [])
        if not existing:
            p = Project(
                id=new_id(), developer_id=dev.id, project_code=code, slug=slug, name=name,
                description=f"{name} is a verified development in {area}.",
                location_name=area, site_latitude=lat, site_longitude=lng, gps_radius_metres=120.0,
                total_units=units, status="construction" if progress < 100 else "completed",
                is_public=True, estimated_completion=datetime(2027, 9, 30, tzinfo=timezone.utc),
                visibility_description=(f"{name} delivers {units} units in {area.split(',')[0]}. "
                                        "Construction progress is GPS-verified and admin-reviewed."),
                visibility_tagline=f"Location-verified construction in {area.split(',')[0]}.",
                starting_price=random.choice(["KES 6.8M", "KES 9.2M", "KES 12.5M", "KES 18M", "KES 24M"]),
                construction_progress=progress, health_status=health,
                activity_overdue_threshold_days=14,
                visibility_page_published=published,
                project_type_id=tpl_obj.project_type_id if tpl_obj else None,
                workflow_template_id=tpl_obj.id if tpl_obj else None,
                created_at=now - timedelta(days=200), updated_at=now,
            )
            db.add(p)
            await db.flush()
            print(f"  Created project: {name} ({code})")
        else:
            p = existing
            p.construction_progress = progress
            p.health_status = health
            p.visibility_page_published = published
            p.slug = p.slug or slug
            await db.flush()
        await create_milestones(db, p, tpl_stages, progress, now)
        projects.append((p, dev, 6 if published else 3, latest, pending, flagged))

    # ── Uploads + photos ───────────────────────────────────────────────────
    print("\n=== Construction updates (uploads) ===")
    total_uploads = 0
    for (p, dev, count, latest, pending, flagged) in projects:
        c = await create_uploads_for_project(db, p, dev.id, images, count, latest, now,
                                              pending=pending, flagged=flagged)
        total_uploads += c
    await db.commit()
    print(f"  Created {total_uploads} new uploads")

    # ── Buyers ──────────────────────────────────────────────────────────────
    print("\n=== Buyers ===")
    first_names = ["James", "Mary", "Peter", "Faith", "Brian", "Aisha", "Kevin", "Wanjiru", "Samuel",
                   "Grace", "David", "Mercy", "Daniel", "Esther", "Joseph", "Lucy", "Michael", "Janet",
                   "Tony", "Nadia", "Ali", "Sophia", "Mark", "Cynthia", "Paul", "Linda", "Victor", "Ruth",
                   "Henry", "Diana", "Felix", "Carol"]
    last_names = ["Mwangi", "Otieno", "Kamau", "Achieng", "Njoroge", "Hassan", "Kiprono", "Wambui",
                  "Omondi", "Mutua", "Chebet", "Karanja", "Abdi", "Nyong'o", "Were", "Maina"]
    diaspora = ["London, UK", "Toronto, Canada", "Dubai, UAE", "Boston, USA", "Sydney, Australia"]
    locals_ = ["Nairobi, Kenya", "Mombasa, Kenya", "Kisumu, Kenya", "Nakuru, Kenya", "Kampala, Uganda"]
    published_projects = [t for t in projects if t[0].visibility_page_published]
    buyer_n = 0
    target_buyers = 32
    bi = 0
    while buyer_n < target_buyers:
        p = projects[bi % len(projects)][0]
        fn = first_names[bi % len(first_names)]
        ln = last_names[bi % len(last_names)]
        email = f"{fn.lower()}.{ln.lower().replace(chr(39),'')}{bi}@buyermail.com"
        loc = (diaspora + locals_)[bi % (len(diaspora) + len(locals_))]
        await create_buyer(db, p, email, f"{fn} {ln}", f"U{100 + bi}", role_map, admin.id, now,
                           phone=f"+2547{random.randint(10000000, 99999999)}")
        buyer_n += 1
        bi += 1
    # named test buyers on a published project
    tp = published_projects[0][0]
    await create_buyer(db, tp, "buyer.diaspora@test.com", "Diaspora Buyer", "A101", role_map, admin.id, now, "+447700900111")
    await create_buyer(db, tp, "buyer.nairobi@test.com", "Nairobi Buyer", "A102", role_map, admin.id, now, "+254700111222")
    await db.commit()
    print(f"  Created ~{buyer_n + 2} buyers across projects")

    # ── Inquiries ─────────────────────────────────────────────────────────
    print("\n=== Inquiries (leads) ===")
    inq_count = (await db.execute(select(func.count()).select_from(Inquiry))).scalar_one()
    if inq_count < 15:
        sources = ["visibility_page", "directory_card", "home_page"]
        for i in range(15):
            p, dev = published_projects[i % len(published_projects)][0], None
            dev_id = p.developer_id
            fn, ln = first_names[i % len(first_names)], last_names[(i + 3) % len(last_names)]
            email = f"lead.{fn.lower()}{i}@prospect.com"
            seen = i % 3 != 0
            created = now - timedelta(days=random.randint(0, 40))
            db.add(Inquiry(
                id=new_id(), project_id=p.id, developer_id=dev_id,
                first_name=fn, last_name=ln, email=email,
                phone=f"+2547{random.randint(10000000,99999999)}",
                location=(diaspora + locals_)[i % (len(diaspora) + len(locals_))],
                message="I am interested in this development. Please share pricing and payment plan.",
                source=sources[i % len(sources)], seen_by_developer=seen,
                seen_at=created + timedelta(hours=5) if seen else None,
                converted_at=(created + timedelta(days=3)) if i in (2, 7) else None,
                ip_address=f"196.201.{random.randint(1,254)}.{random.randint(1,254)}",
                user_agent="Mozilla/5.0 (seed)", created_at=created,
            ))
        await db.commit()
        print("  Created 15 inquiries")
    else:
        print(f"  Inquiries already present ({inq_count})")

    # ── Visibility page views ────────────────────────────────────────────
    print("\n=== Visibility page views ===")
    view_count = (await db.execute(select(func.count()).select_from(VisibilityPageView))).scalar_one()
    if view_count < 150:
        rows = 0
        for (p, *_rest) in published_projects:
            for _ in range(random.randint(28, 45)):
                viewed = now - timedelta(days=random.randint(0, 45), minutes=random.randint(0, 1440))
                db.add(VisibilityPageView(
                    id=new_id(), project_id=p.id, session_id=new_id(),
                    country_code=random.choice(COUNTRIES),
                    duration_seconds=random.randint(8, 240),
                    referrer=random.choice(["direct", "whatsapp", "https://google.com", "instagram", None]),
                    viewed_at=viewed,
                ))
                rows += 1
            p.visibility_page_views = (p.visibility_page_views or 0) + rows
        await db.commit()
        print(f"  Created {rows} visibility page views")
    else:
        print(f"  Views already present ({view_count})")

    # ── Notification log ─────────────────────────────────────────────────
    print("\n=== Notification log ===")
    notif_count = (await db.execute(
        select(func.count()).select_from(NotificationLog).where(NotificationLog.template_name == "upload_notification")
    )).scalar_one()
    if notif_count < 50:
        for i in range(55):
            p, dev = published_projects[i % len(published_projects)][0], None
            failed = i % 9 == 0
            db.add(NotificationLog(
                id=new_id(), developer_id=p.developer_id, notification_type="email",
                recipient_email=f"buyer{i}@buyermail.com",
                subject="New verified construction update",
                template_name="upload_notification",
                status="failed" if failed else random.choice(["sent", "delivered", "delivered"]),
                error_message="SMTP timeout" if failed else None,
                created_at=now - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23)),
            ))
        await db.commit()
        print("  Created 55 notification log entries")
    else:
        print(f"  Notification log already present ({notif_count})")

    # ── Audit log ──────────────────────────────────────────────────────────
    print("\n=== Audit log ===")
    audit_count = (await db.execute(
        text("SELECT count(*) FROM audit_log WHERE request_id = 'seed-demo'")
    )).scalar_one()
    if audit_count < 100:
        actions = [
            ("upload.approved", "upload"), ("upload.rejected.gps_outside_boundary", "upload_attempt"),
            ("milestone.completed", "milestone"), ("milestone.delayed", "milestone"),
            ("buyer.invited", "buyer"), ("inquiry.created", "inquiry"),
            ("project.visibility.published", "project"), ("project.created", "project"),
            ("member.invited", "member"),
        ]
        dev_ids = [acoma.id if acoma else skyline.id, skyline.id, greenline.id]
        for i in range(120):
            act, ent = actions[i % len(actions)]
            await db.execute(text("""
                INSERT INTO audit_log (id, actor_user_id, actor_role, action, entity_type, entity_id,
                    developer_id, before_state, after_state, metadata, ip_address, user_agent, request_id, created_at)
                VALUES (:id,:auid,:role,:action,:etype,:eid,:did,NULL,NULL,NULL,:ip,'seed',:rid,:ts)
            """), {
                "id": new_id(), "auid": admin.id, "role": "admin", "action": act,
                "etype": ent, "eid": new_id(), "did": dev_ids[i % len(dev_ids)],
                "ip": f"196.201.{random.randint(1,254)}.{random.randint(1,254)}",
                "rid": "seed-demo", "ts": now - timedelta(days=random.randint(0, 75), hours=random.randint(0, 23)),
            })
        await db.commit()
        print("  Created 120 audit log entries")
    else:
        print(f"  Audit log already present ({audit_count})")

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("DEMO SEED COMPLETE")
    print("=" * 60)
    print("Logins (password):")
    print("  Admin           admin@buildtrack.co.ke    / Admin@2026!")
    print("  Dev (Acoma)     developer@acme.co.ke      / Developer@2026!")
    print("  Site Manager    site.manager@acme.co.ke   / Manager@2026!")
    print("  Dev (Skyline)   owner@skyline.co.ke       / Developer@2026!")
    print("  Dev (Greenline) owner@greenline.co.ke     / Developer@2026!")
    print("  Buyers          buyer.diaspora@test.com, buyer.nairobi@test.com / Buyer@2026!")
    print("\nPublished visibility pages (http://localhost:3000/developments/<slug>):")
    res = await db.execute(select(Project).where(Project.visibility_page_published == True))  # noqa: E712
    for p in res.scalars().all():
        print(f"  /developments/{p.slug}   ({p.name}, {p.construction_progress}%)")
    print("\nDirectory: http://localhost:3000/developments")


async def main():
    async with async_session_factory() as db:
        await seed_demo(db)


if __name__ == "__main__":
    asyncio.run(main())
