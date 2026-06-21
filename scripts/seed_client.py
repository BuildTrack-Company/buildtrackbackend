"""
Seed the BuildTrack database with the client's three demo projects
(Luna Oak Residency, Highpoint 336 Residence, Express View Residency),
plus developer profiles, milestones, construction updates (with real
Cloudinary images), buyers, subscriptions and payments.

Also uploads the local sample images to Cloudinary and backfills any
pre-existing projects so nothing shows a blank image.

Run: backend/.venv/bin/python scripts/seed_client.py
"""
import asyncio
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import cloudinary
import cloudinary.uploader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.security import hash_password
from app.shared.ids import new_id
from app.shared.storage import get_signed_url

from app.modules.auth.models import User
from app.modules.developers.models import Developer
from app.modules.projects.models import Project
from app.modules.milestones.models import Milestone
from app.modules.buyers.models import Buyer
from app.modules.uploads.models import Upload, Photo
from app.modules.members.models import DeveloperMember
from app.modules.roles.models import UserRoleAssignment
from app.modules.settings.models import TenantSetting
from app.modules.billing.models import SubscriptionPayment

# Reuse the canonical system seeders (project types, workflows, roles, settings)
from scripts.seed_dev import (
    seed_project_types,
    seed_permissions_and_roles,
    seed_system_settings,
)

IMAGES_DIR = "/Users/lawrence/projects/buildtrack/images"
CACHE_FILE = "/tmp/bt_cloudinary_seed_map.json"


def D(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


# ───────────────────────── Cloudinary image upload ──────────────────────────
def _sorted_images() -> list[str]:
    return sorted(
        os.path.join(IMAGES_DIR, f)
        for f in os.listdir(IMAGES_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )


def upload_images() -> list[str]:
    """Upload (resized) local images to Cloudinary, returning a list of
    public_ids indexed the same as the sorted file list. Cached to disk."""
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    files = _sorted_images()
    cache = {}
    if os.path.exists(CACHE_FILE):
        cache = json.load(open(CACHE_FILE))

    public_ids: list[str] = []
    for i, path in enumerate(files):
        key = os.path.basename(path)
        if key in cache:
            public_ids.append(cache[key])
            continue
        # Resize to keep well under Cloudinary limits and speed things up.
        img = Image.open(path).convert("RGB")
        img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        buf.seek(0)
        pid = f"{settings.CLOUDINARY_FOLDER_ROOT}/seed/img_{i:02d}"
        res = cloudinary.uploader.upload(
            buf, public_id=pid, overwrite=True, resource_type="image"
        )
        cache[key] = res["public_id"]
        public_ids.append(res["public_id"])
        json.dump(cache, open(CACHE_FILE, "w"), indent=2)
        print(f"  uploaded {key} -> {res['public_id']}")
    return public_ids


def delivery_url(public_id: str) -> str:
    return f"https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/image/upload/q_auto,f_auto,w_1600/{public_id}"


# ───────────────────────── helpers ──────────────────────────
async def get_or_create_user(db, email, password, full_name, role, now):
    u = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if u:
        return u
    u = User(
        id=new_id(), email=email, hashed_password=hash_password(password),
        role=role, full_name=full_name, is_active=True, email_verified=True,
        created_at=now, updated_at=now,
    )
    db.add(u)
    await db.flush()
    return u


async def add_photos(db, upload, img_ids, cap_lat, cap_lng, when):
    for idx, pid in enumerate(img_ids):
        db.add(Photo(
            id=new_id(), upload_id=upload.id,
            cloudinary_public_id=pid, cloudinary_url=delivery_url(pid),
            original_filename=f"{upload.idempotency_key}_{idx+1}.jpg",
            capture_latitude=cap_lat, capture_longitude=cap_lng,
            accuracy_m=8.0, order_index=idx, width=1600, height=1067,
            file_size_bytes=450000, created_at=when,
        ))


# ───────────────────────── client data ──────────────────────────
def build_projects(IMG):
    """Return the three developer/project payloads. IMG = list of public_ids."""
    # image pools by construction stage (indices into the sorted image list)
    LEGAL = [IMG[3], IMG[12], IMG[8], IMG[2], IMG[26]]
    EXCAV = [IMG[25], IMG[28], IMG[29], IMG[10], IMG[16]]
    FOUND = [IMG[19], IMG[23], IMG[22], IMG[14], IMG[13]]
    SUPER = [IMG[0], IMG[1], IMG[6], IMG[7], IMG[9], IMG[15], IMG[20], IMG[27], IMG[30], IMG[5]]

    return [
        {
            "dev": dict(
                email="oakgroup@buildtrack.co.ke", password="Oak@2026!",
                contact="Daniel Mwangi", company="The Oak Group Residences",
                years=19, completed=5, active=6, freq_days=7.0, consistency=94.0,
                tier="large", website="https://oakgroupresidences.co.ke",
                address="Kilungu Road, Kilimani, Nairobi",
                overview="The Oak Group Residences delivers premium high-rise residential developments across Nairobi, with a 94% update-consistency track record over 19 years.",
            ),
            "project": dict(
                code="LUNA01", slug="luna-oak-residency", name="Luna Oak Residency",
                location="Kilungu Road, Kilimani, Nairobi", lat=-1.294011, lng=36.777434,
                units=294, progress=28, completion=D(2029, 9, 30), threshold=7,
                tagline="Elegant 25-floor living on Kilungu Road, Kilimani.",
                description="Luna Oak Residency is a thoughtfully designed high-rise residential development on Kilungu Road in Kilimani, near Cavina School. Rising 25 floors with units from the 3rd to the 25th floor, the project offers an ideal blend of elegance, comfort, and long-term investment value.",
                starting_price="From KES 9.5M",
            ),
            "milestones": [
                ("Legal and Title Clearance", "complete", D(2024, 3, 31), D(2024, 3, 14)),
                ("Foundation Complete", "complete", D(2025, 2, 28), D(2025, 2, 15)),
                ("Superstructure Complete", "in_progress", D(2026, 8, 31), None),
                ("Building Envelope and Roofing", "pending", D(2027, 6, 30), None),
                ("Practical Completion", "pending", D(2029, 9, 30), None),
            ],
            "updates": [
                ("Legal and Administrative", "Title Clearance and Site Handover Confirmed — Milestone 1 of 5", D(2024, 3, 14), 5, 1,
                 "All legal documentation for Luna Oak Residency has been verified and cleared. Title deeds are in order, and the site on Kilungu Road has been formally handed over to the construction team. Boundary pegs are in place, and site hoarding has been erected. Construction mobilization begins next week.", LEGAL[:2]),
                ("Structural Works", "Excavation and Piling Works Complete", D(2024, 6, 28), 12, 2,
                 "Excavation works across the full footprint of the site have been completed to the required depth. Piling works have been successfully carried out with 186 piles installed and load tested. Structural engineers have signed off on the piling report. Substructure works and foundation casting are now underway.", [EXCAV[0], EXCAV[1]]),
                ("Milestone Completed", "Foundation Works Complete — Milestone 2 of 5", D(2025, 2, 15), 18, 2,
                 "Foundation works for Luna Oak Residency are now fully complete. All ground beams, pile caps, and slab on grade have been cast and cured to specification. Structural integrity has been independently confirmed. The project now transitions to superstructure works, beginning with ground floor columns and slabs. This marks the completion of Milestone 2 of 5.", [FOUND[0], FOUND[1]]),
                ("Structural Works", "Superstructure Progress — Floors 1 to 8 Complete", D(2025, 9, 3), 22, 3,
                 "Superstructure works are progressing steadily. Columns, beams, and suspended slabs for floors 1 through 8 have been cast and cured. Formwork is currently being struck on floor 7 while casting continues on floor 9. The structural team is maintaining a floor-per-three-weeks cycle. No delays recorded at this stage.", [SUPER[1], SUPER[2]]),
                ("Structural Works", "Superstructure Progress — Floors 9 to 15 Complete", D(2026, 1, 12), 25, 3,
                 "The superstructure has now reached floor 15. Works on floors 9 through 15, including columns, suspended slabs, and staircase cores, are complete and cured. The project remains on schedule relative to the superstructure completion target of August 2026. Block work for partition walls is commencing on the lower floors in parallel with ongoing structural works above.", [SUPER[5], SUPER[6]]),
                ("Structural Works", "Superstructure Progress — Floors 16 to 19 Complete", D(2026, 6, 11), 28, 3,
                 "Superstructure works continue on schedule. Floors 16 through 19 have been fully cast and cured. The team is currently casting floor 20 with floors 21 through 25 remaining. Parallel works on the lower floors include block work for internal partition walls on floors 3 through 10 and MEP conduit installation on floors 3 through 7. The project remains on track for Milestone 3 completion in August 2026.", [SUPER[7], SUPER[3]]),
            ],
            "cover": SUPER[5],
            "buyers": [
                ("alice.wanjiru@gmail.com", "Alice Wanjiru", "A0304", "+254712345001", True),
                ("brian.otieno@gmail.com", "Brian Otieno", "B1102", "+254712345002", True),
                ("carol.njeri@yahoo.com", "Carol Njeri", "C0708", "+254712345003", False),
                ("david.kamau@gmail.com", "David Kamau", "A1501", "+254712345004", False),
                ("esther.akinyi@gmail.com", "Esther Akinyi", "D2003", "+254712345005", False),
                ("frank.mutua@outlook.com", "Frank Mutua", "B0905", "+254712345006", False),
            ],
            # fully paid developer
            "billing": dict(start=D(2024, 3, 1), amount=52000, pattern="full"),
        },
        {
            "dev": dict(
                email="highpoint@buildtrack.co.ke", password="Highpoint@2026!",
                contact="Faith Chebet", company="Highpoint Residences Ltd",
                years=10, completed=9, active=1, freq_days=14.0, consistency=91.0,
                tier="large", website="https://highpointresidences.co.ke",
                address="Kilimani Road, Nairobi",
                overview="Highpoint Residences Ltd has delivered 9 completed developments over more than a decade, focused on modern, European-standard apartment living in Kilimani.",
            ),
            "project": dict(
                code="HIGH336", slug="highpoint-336-residence", name="Highpoint 336 Residence",
                location="Kilimani Road, Nairobi", lat=-1.298320, lng=36.780929,
                units=336, progress=35, completion=D(2028, 6, 30), threshold=14,
                tagline="Modern elegance with floor-to-ceiling Kilimani skyline views.",
                description="Each apartment at Highpoint 336 is a study in modern elegance. Spacious layouts. European-standard kitchens. Fitted wardrobes. Floor-to-ceiling windows that frame Kilimani's skyline.",
                starting_price="From KES 8.2M",
            ),
            "milestones": [
                ("Legal and Title Clearance", "complete", D(2023, 1, 31), D(2023, 1, 10)),
                ("Foundation Complete", "complete", D(2023, 11, 30), D(2023, 11, 22)),
                ("Superstructure Complete", "in_progress", D(2026, 12, 31), None),
                ("Building Envelope and Roofing", "pending", D(2027, 8, 31), None),
                ("Practical Completion", "pending", D(2028, 6, 30), None),
            ],
            "updates": [
                ("Legal and Administrative", "Site Acquisition and Title Clearance Confirmed — Milestone 1 of 5", D(2023, 1, 10), 5, 1,
                 "Legal and title clearance for the Highpoint 336 site on Kilimani Road has been completed. All statutory approvals, including the NCA project registration and county building permit, are in place. Site hoarding and security have been established. This confirms the completion of Milestone 1 of 5 and marks the formal commencement of the project.", [LEGAL[2], LEGAL[4]]),
                ("Milestone Completed", "Foundation Works Complete — Milestone 2 of 5", D(2023, 11, 22), 14, 2,
                 "Foundation works for Highpoint 336 are complete. Piling, pile caps, ground beams, and the slab on grade have been successfully cast and independently verified. The structural engineer's sign-off has been received. The project now advances to superstructure works. This marks the completion of Milestone 2 of 5.", [FOUND[2], FOUND[3]]),
                ("Structural Works", "Superstructure Progress — Ground Floor to Level 5 Complete", D(2024, 5, 18), 20, 3,
                 "Superstructure works have commenced and are progressing well. Columns, beams, and suspended slabs from the ground floor through to level 5 have been cast and cured. The structural frame is taking shape and is visible from Kilimani Road. No structural issues have been recorded. Works are proceeding in line with the programme.", [SUPER[0], SUPER[4]]),
                ("Structural Works", "Superstructure Progress — Levels 6 to 12 Complete", D(2024, 10, 30), 27, 3,
                 "The superstructure has reached level 12. All columns, suspended slabs, and staircase cores from levels 6 through 12 are complete and cured. Formwork striking is underway on level 11. Block work for internal partition walls is commencing on levels 1 through 4 concurrently with ongoing structural works on the upper floors.", [SUPER[9], SUPER[8]]),
                ("Structural Works", "Design Enhancement Works — Wider Lift Lobbies and Staircase Upgrades Incorporated", D(2025, 3, 14), 31, 3,
                 "Following a design review, structural enhancements have been incorporated into the ongoing superstructure works. These include wider lift lobbies, improved staircase widths, and enhanced accessibility features on all floors. These upgrades have been fully integrated into the structural programme. The revised design is now reflected in all floors from level 13 upward. The project timeline has been reviewed, and the Q2 2028 completion date remains the target.", [SUPER[6], SUPER[2]]),
                ("Structural Works", "Superstructure Progress — Levels 13 to 19 Complete", D(2026, 6, 10), 35, 3,
                 "Superstructure works continue steadily, incorporating the enhanced design specifications. Levels 13 through 19 are fully cast and cured. The team is currently working on level 20. MEP rough-in works, including electrical conduits and plumbing sleeves, are progressing on levels 1 through 8. Internal block work is complete on levels 1 through 6. The project is tracking toward Milestone 3 completion in December 2026.", [SUPER[5], SUPER[7]]),
            ],
            "cover": SUPER[7],
            "buyers": [
                ("grace.mumbi@gmail.com", "Grace Mumbi", "GF-201", "+254713345001", True),
                ("henry.kiprop@gmail.com", "Henry Kiprop", "L5-12", "+254713345002", True),
                ("irene.wairimu@yahoo.com", "Irene Wairimu", "L8-04", "+254713345003", False),
                ("james.omondi@gmail.com", "James Omondi", "L3-09", "+254713345004", False),
                ("lucy.cherono@gmail.com", "Lucy Cherono", "L11-02", "+254713345005", False),
            ],
            # partially paid developer
            "billing": dict(start=D(2023, 1, 1), amount=52000, pattern="partial"),
        },
        {
            "dev": dict(
                email="lanagroup@buildtrack.co.ke", password="Lana@2026!",
                contact="Samuel Kariuki", company="Lana Group",
                years=5, completed=3, active=1, freq_days=7.0, consistency=88.0,
                tier="medium", website="https://lanagroup.co.ke",
                address="Riara Road, Kilimani, Nairobi",
                overview="Lana Group builds family-focused residential developments in green, well-connected Nairobi neighbourhoods, with 3 completed projects to date.",
            ),
            "project": dict(
                code="EXPVIEW", slug="express-view-residency", name="Express View Residency",
                location="Riara Road, Kilimani, Nairobi", lat=-1.297591, lng=36.767496,
                units=200, progress=30, completion=D(2028, 12, 31), threshold=7,
                tagline="Quiet, green family living with open views off Riara Road.",
                description="Express View is set in a quiet, green neighbourhood with open views. Conveniently located close to schools, shopping malls, churches, and hospitals. Designed for family living or long-term investment rental.",
                starting_price="From KES 6.8M",
            ),
            "milestones": [
                ("Legal and Title Clearance", "complete", D(2025, 5, 31), D(2025, 5, 12)),
                ("Foundation Complete", "complete", D(2026, 1, 31), D(2026, 1, 15)),
                ("Superstructure Complete", "in_progress", D(2027, 2, 28), None),
                ("Building Envelope and Roofing", "pending", D(2027, 10, 31), None),
                ("Practical Completion", "pending", D(2028, 12, 31), None),
            ],
            "updates": [
                ("Legal and Administrative", "Site Clearance and Title Verification Complete — Milestone 1 of 5", D(2025, 5, 12), 5, 1,
                 "All legal and title documentation for Express View Residency on Riara Road has been verified and cleared. The county building permit and NCA project registration are in place. Site clearance and hoarding have been completed. The project is formally registered, and construction mobilization is underway. This marks the completion of Milestone 1 of 5.", [LEGAL[1], LEGAL[3]]),
                ("Structural Works", "Excavation Complete and Foundation Works Underway", D(2025, 9, 8), 12, 2,
                 "Bulk excavation across the full site footprint has been completed. Piling works are underway with approximately 60% of piles installed and load tested. Blinding concrete has been laid across the excavated areas. Foundation casting is expected to commence within the next three weeks, pending completion of the remaining piling works.", [EXCAV[2], EXCAV[3]]),
                ("Milestone Completed", "Foundation Works Complete — Milestone 2 of 5", D(2026, 1, 15), 18, 2,
                 "Foundation works for Express View Residency are now complete. All piling, pile caps, ground beams, and slab on grade have been successfully cast, cured, and independently verified. Structural sign-off has been received. The project now advances to superstructure works, beginning with ground floor columns. This marks the completion of Milestone 2 of 5.", [FOUND[1], FOUND[0]]),
                ("Structural Works", "Superstructure Commenced — Ground Floor Columns and Slab Complete", D(2026, 3, 22), 23, 3,
                 "Superstructure works have commenced at Express View Residency. Ground floor columns and the first suspended slab have been successfully cast and cured. The structural frame is now above ground and visible from Riara Road. Works are proceeding on schedule, and the team is currently casting level 1 columns. No delays have been recorded.", [SUPER[2], SUPER[1]]),
                ("Structural Works", "Superstructure Progress — Levels 1 to 4 Complete", D(2026, 5, 28), 27, 3,
                 "Superstructure works are progressing steadily. Levels 1 through 4, including columns, beams, and suspended slabs, are complete and cured. The team is currently casting level 5 columns. The project is on track relative to the superstructure completion target of February 2027. No structural issues have been recorded to date.", [SUPER[3], SUPER[4]]),
                ("Structural Works", "Superstructure Progress — Level 5 Slab Cast", D(2026, 6, 15), 30, 3,
                 "Level 5 slab has been successfully cast at Express View Residency. The pour was completed without incident, and curing is currently underway. Formwork will be struck on level 4 next week. The project continues on programme with level 6 columns scheduled to commence within the next ten days. MEP sleeve installation is progressing on levels 1 and 2 concurrently with ongoing structural works.", [SUPER[8], SUPER[9]]),
            ],
            "cover": SUPER[3],
            "buyers": [
                ("mary.atieno@gmail.com", "Mary Atieno", "1-A2", "+254714345001", True),
                ("nelson.gitau@gmail.com", "Nelson Gitau", "2-B4", "+254714345002", True),
                ("olive.kerubo@yahoo.com", "Olive Kerubo", "3-C1", "+254714345003", False),
                ("peter.mwende@gmail.com", "Peter Mwende", "4-D3", "+254714345004", False),
                ("rachel.nasimiyu@gmail.com", "Rachel Nasimiyu", "1-A5", "+254714345005", False),
            ],
            # mostly paid, one partial
            "billing": dict(start=D(2025, 5, 1), amount=32000, pattern="mixed"),
        },
    ]


def build_payments(developer_id, billing, now):
    """Generate monthly invoice/payment rows from start to now."""
    start = billing["start"]
    amount = billing["amount"]
    pattern = billing["pattern"]
    rows = []
    y, m = start.year, start.month
    months = []
    while (y < now.year) or (y == now.year and m <= now.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    for i, (yy, mm) in enumerate(months):
        ps = D(yy, mm, 1)
        em, ey = (mm + 1, yy) if mm < 12 else (1, yy + 1)
        pe = D(ey, em, 1)
        remaining = len(months) - 1 - i  # 0 == current month
        if pattern == "full":
            paid, status = amount, "paid"
        elif pattern == "partial":
            if remaining == 0:
                paid, status = 0, "pending"
            elif remaining == 1:
                paid, status = amount // 2, "partial"
            else:
                paid, status = amount, "paid"
        else:  # mixed
            if remaining == 0:
                paid, status = int(amount * 0.6), "partial"
            else:
                paid, status = amount, "paid"
        method = ["mpesa", "bank_transfer", "card"][i % 3] if paid else None
        rows.append(SubscriptionPayment(
            id=new_id(), developer_id=developer_id, tier=billing.get("tier", "medium"),
            period_start=ps, period_end=pe, amount_due_kes=amount, amount_paid_kes=paid,
            status=status, method=method,
            reference=(f"BT-{yy}{mm:02d}-{developer_id[:6].upper()}" if paid else None),
            paid_at=(ps if paid else None), created_at=ps, updated_at=now,
        ))
    return rows


# ───────────────────────── main seed ──────────────────────────
async def seed(db: AsyncSession, IMG):
    now = datetime.now(timezone.utc)
    templates_map = await seed_project_types(db)
    role_map = await seed_permissions_and_roles(db)
    await seed_system_settings(db)

    admin = (await db.execute(select(User).where(User.email == "admin@buildtrack.co.ke"))).scalar_one_or_none()
    admin_id = admin.id if admin else None

    apt_tmpl, apt_stages = templates_map.get("Off-Plan Apartment", (None, []))
    stage_by_name = {s.name: s for s in apt_stages}
    ms_to_stage = {
        "Legal and Title Clearance": "Pre-Construction",
        "Foundation Complete": "Foundation",
        "Superstructure Complete": "Superstructure",
        "Building Envelope and Roofing": "Building Envelope",
        "Practical Completion": "Practical Completion",
    }

    for payload in build_projects(IMG):
        dv = payload["dev"]
        print(f"\n=== {dv['company']} ===")
        user = await get_or_create_user(db, dv["email"], dv["password"], dv["contact"], "developer", now)

        developer = (await db.execute(select(Developer).where(Developer.user_id == user.id))).scalar_one_or_none()
        if not developer:
            developer = Developer(id=new_id(), user_id=user.id)
            db.add(developer)
        developer.company_name = dv["company"]
        developer.contact_name = dv["contact"]
        developer.years_operating = dv["years"]
        developer.projects_completed = dv["completed"]
        developer.active_developments = dv["active"]
        developer.avg_update_frequency_days = dv["freq_days"]
        developer.update_consistency_pct = dv["consistency"]
        developer.company_overview = dv["overview"]
        developer.subscription_tier = dv["tier"]
        developer.subscription_status = "active"
        developer.subscription_expires_at = D(2026, 12, 31)
        developer.website = dv["website"]
        developer.address = dv["address"]
        developer.updated_at = now
        await db.flush()

        # org membership + role
        if not (await db.execute(select(DeveloperMember).where(
            DeveloperMember.developer_id == developer.id, DeveloperMember.user_id == user.id
        ))).scalar_one_or_none():
            db.add(DeveloperMember(
                id=new_id(), developer_id=developer.id, user_id=user.id, org_role="owner",
                invited_by=user.id, invited_at=now, joined_at=now, is_active=True, created_at=now,
            ))
        if "developer_owner" in role_map and not (await db.execute(select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user.id,
            UserRoleAssignment.role_id == role_map["developer_owner"].id,
            UserRoleAssignment.developer_id == developer.id,
        ))).scalar_one_or_none():
            db.add(UserRoleAssignment(
                id=new_id(), user_id=user.id, role_id=role_map["developer_owner"].id,
                developer_id=developer.id, granted_by=admin_id or user.id,
                granted_at=now, created_at=now,
            ))

        # tenant settings
        for k, v in {
            "notification_on_upload_approved": "true",
            "notification_on_milestone_complete": "true",
            "upload_require_caption": "true",
            "upload_min_photos": "1", "upload_max_photos": "20",
        }.items():
            if not (await db.execute(select(TenantSetting).where(
                TenantSetting.developer_id == developer.id, TenantSetting.key == k
            ))).scalar_one_or_none():
                db.add(TenantSetting(id=new_id(), developer_id=developer.id, key=k, value=v, updated_at=now, created_at=now))
        await db.flush()

        # project
        pj = payload["project"]
        project = (await db.execute(select(Project).where(Project.project_code == pj["code"]))).scalar_one_or_none()
        if not project:
            project = Project(id=new_id(), developer_id=developer.id, project_code=pj["code"])
            db.add(project)
        project.developer_id = developer.id
        project.slug = pj["slug"]
        project.name = pj["name"]
        project.description = pj["description"]
        project.location_name = pj["location"]
        project.site_latitude = pj["lat"]
        project.site_longitude = pj["lng"]
        project.gps_radius_metres = 150.0
        project.total_units = pj["units"]
        project.status = "construction"
        project.cover_image_url = delivery_url(payload["cover"])
        project.estimated_completion = pj["completion"]
        project.is_public = True
        project.visibility_description = pj["description"]
        project.visibility_tagline = pj["tagline"]
        project.starting_price = pj["starting_price"]
        project.construction_progress = pj["progress"]
        project.health_status = "on_schedule"
        project.activity_overdue_threshold_days = pj["threshold"]
        project.visibility_page_published = True
        project.project_type_id = apt_tmpl.project_type_id if apt_tmpl else None
        project.workflow_template_id = apt_tmpl.id if apt_tmpl else None
        project.updated_at = now
        await db.flush()

        # milestones
        existing_ms = (await db.execute(select(Milestone).where(Milestone.project_id == project.id))).scalars().all()
        ms_by_name = {m.name: m for m in existing_ms}
        in_progress_stage_id = None
        for order, (mname, status, exp, done) in enumerate(payload["milestones"], start=1):
            stage = stage_by_name.get(ms_to_stage.get(mname, ""))
            m = ms_by_name.get(mname)
            if not m:
                m = Milestone(id=new_id(), project_id=project.id, name=mname, created_at=now)
                db.add(m)
            m.order_index = order
            m.status = status
            m.expected_date = exp
            m.completed_at = done
            m.workflow_stage_id = stage.id if stage else None
            m.updated_at = now
            if status == "in_progress" and stage:
                in_progress_stage_id = stage.id
            ms_by_name[mname] = m
        if in_progress_stage_id:
            project.current_stage_id = in_progress_stage_id
        await db.flush()

        # construction updates (uploads + photos)
        for n, (cat, title, when, prog, ms_order, desc, imgs) in enumerate(payload["updates"], start=1):
            idem = f"seed_{pj['code']}_u{n}"
            up = (await db.execute(select(Upload).where(Upload.idempotency_key == idem))).scalar_one_or_none()
            if up:
                continue
            milestone = None
            mnames = [x[0] for x in payload["milestones"]]
            if 1 <= ms_order <= len(mnames):
                milestone = ms_by_name.get(mnames[ms_order - 1])
            up = Upload(
                id=new_id(), project_id=project.id, developer_id=developer.id,
                milestone_id=milestone.id if milestone else None, idempotency_key=idem,
                title=title, category=cat, caption=desc, progress_at_upload=prog,
                capture_latitude=pj["lat"], capture_longitude=pj["lng"],
                accuracy_m=8.0, distance_from_site_m=12.0, within_boundary=True,
                gps_validated=True, photo_count=len(imgs), status="approved",
                reviewed_at=when, reviewed_by=admin_id,
                notification_fanout_status="complete", notification_fanout_at=when,
                created_at=when, updated_at=when,
            )
            db.add(up)
            await db.flush()
            await add_photos(db, up, imgs, pj["lat"], pj["lng"], when)
        await db.flush()

        # buyers
        for email, name, unit, phone, registered in payload["buyers"]:
            if (await db.execute(select(Buyer).where(Buyer.email == email, Buyer.project_id == project.id))).scalar_one_or_none():
                continue
            buyer_user_id = None
            if registered:
                bu = await get_or_create_user(db, email, "Buyer@2026!", name, "buyer", now)
                buyer_user_id = bu.id
                if "buyer_viewer" in role_map and not (await db.execute(select(UserRoleAssignment).where(
                    UserRoleAssignment.user_id == bu.id, UserRoleAssignment.role_id == role_map["buyer_viewer"].id
                ))).scalar_one_or_none():
                    db.add(UserRoleAssignment(
                        id=new_id(), user_id=bu.id, role_id=role_map["buyer_viewer"].id,
                        granted_by=admin_id or user.id, granted_at=now, created_at=now,
                    ))
            db.add(Buyer(
                id=new_id(), user_id=buyer_user_id, project_id=project.id, email=email,
                full_name=name, phone=phone, unit_number=unit,
                invitation_sent_at=now, registered_at=(now if registered else None),
                notification_email=True, created_at=now, updated_at=now,
            ))
        await db.flush()

        # payments
        if not (await db.execute(select(SubscriptionPayment).where(SubscriptionPayment.developer_id == developer.id))).scalars().first():
            billing = dict(payload["billing"]); billing["tier"] = dv["tier"]
            for row in build_payments(developer.id, billing, now):
                db.add(row)
            await db.flush()
        print(f"  seeded project {pj['code']} with milestones, updates, buyers, payments")

    # ── Backfill pre-existing projects so none show a blank image ──
    print("\n=== Backfilling pre-existing projects ===")
    all_projects = (await db.execute(select(Project).where(Project.deleted_at.is_(None)))).scalars().all()
    backfill_imgs = IMG[:]
    bf_i = 0
    for project in all_projects:
        if project.project_code in ("LUNA01", "HIGH336", "EXPVIEW"):
            continue
        changed = False
        if not project.cover_image_url:
            project.cover_image_url = delivery_url(backfill_imgs[bf_i % len(backfill_imgs)])
            bf_i += 1
            changed = True
        has_approved = (await db.execute(select(Upload).where(
            Upload.project_id == project.id, Upload.status == "approved"
        ))).scalars().first()
        if not has_approved:
            idem = f"seed_backfill_{project.id[:8]}"
            if not (await db.execute(select(Upload).where(Upload.idempotency_key == idem))).scalar_one_or_none():
                lat = project.site_latitude or -1.29
                lng = project.site_longitude or 36.82
                up = Upload(
                    id=new_id(), project_id=project.id, developer_id=project.developer_id,
                    idempotency_key=idem, title="Site Progress Update",
                    category="Structural Works",
                    caption="Construction works progressing on site. Structural frame advancing on schedule.",
                    progress_at_upload=project.construction_progress or 20,
                    capture_latitude=lat, capture_longitude=lng, accuracy_m=9.0,
                    distance_from_site_m=15.0, within_boundary=True, gps_validated=True,
                    photo_count=2, status="approved", reviewed_at=now, reviewed_by=admin_id,
                    notification_fanout_status="complete", notification_fanout_at=now,
                    created_at=now, updated_at=now,
                )
                db.add(up)
                await db.flush()
                imgs = [backfill_imgs[bf_i % len(backfill_imgs)], backfill_imgs[(bf_i + 1) % len(backfill_imgs)]]
                bf_i += 2
                await add_photos(db, up, imgs, lat, lng, now)
                changed = True
        if changed:
            if not project.slug:
                project.slug = project.project_code.lower()
            project.visibility_page_published = True
            project.is_public = True
            print(f"  backfilled {project.project_code}")
    await db.commit()
    print("\nSeed complete.")


async def main():
    print("Uploading images to Cloudinary...")
    IMG = upload_images()
    print(f"  {len(IMG)} images ready")
    async with async_session_factory() as db:
        await seed(db, IMG)
    print("\nDeveloper logins:")
    print("  oakgroup@buildtrack.co.ke   / Oak@2026!")
    print("  highpoint@buildtrack.co.ke  / Highpoint@2026!")
    print("  lanagroup@buildtrack.co.ke  / Lana@2026!")


if __name__ == "__main__":
    asyncio.run(main())
