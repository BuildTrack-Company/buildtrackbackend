"""
Seed development database with test data.
Run: .venv/Scripts/python scripts/seed_dev.py
"""
import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
import hashlib
import secrets

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import async_session_factory
from app.core.security import hash_password
from app.shared.ids import new_id
from app.modules.auth.models import User
from app.modules.developers.models import Developer
from app.modules.projects.models import Project
from app.modules.milestones.models import Milestone
from app.modules.buyers.models import Buyer
from app.modules.uploads.models import Upload, Photo


async def seed(db: AsyncSession):
    print("Starting seed...")

    # ─── Admin User ───────────────────────────────────────────────
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
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(admin_user)
        await db.flush()
        print(f"Created admin: {admin_email}")
    else:
        print(f"Admin already exists: {admin_email}")

    # ─── Developer User ───────────────────────────────────────────
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
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(dev_user)
        await db.flush()
        print(f"Created developer user: {dev_email}")
    else:
        print(f"Developer user already exists: {dev_email}")

    # ─── Developer Profile ────────────────────────────────────────
    result = await db.execute(select(Developer).where(Developer.user_id == dev_user.id))
    developer = result.scalar_one_or_none()
    if not developer:
        developer = Developer(
            id=new_id(),
            user_id=dev_user.id,
            company_name="Acoma Developments Ltd",
            subscription_tier="growth",
            subscription_status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(developer)
        await db.flush()
        print(f"Created developer profile: Acoma Developments Ltd")
    else:
        print(f"Developer profile already exists")

    # ─── Project ──────────────────────────────────────────────────
    project_code = "SYCA01"
    result = await db.execute(select(Project).where(Project.project_code == project_code))
    project = result.scalar_one_or_none()
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
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(project)
        await db.flush()
        print(f"Created project: {project.name} ({project_code})")
    else:
        print(f"Project already exists: {project_code}")

    # ─── Milestones ───────────────────────────────────────────────
    result = await db.execute(select(Milestone).where(Milestone.project_id == project.id))
    existing_milestones = result.scalars().all()

    if not existing_milestones:
        milestones_data = [
            {
                "name": "Pre-Construction",
                "order_index": 1,
                "status": "complete",  # PRD enum: pending, in_progress, complete, delayed
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

        now = datetime.now(timezone.utc)
        for m in milestones_data:
            milestone = Milestone(
                id=new_id(),
                project_id=project.id,
                created_at=now,
                updated_at=now,
                **m,
            )
            db.add(milestone)
        await db.flush()
        print(f"Created 5 milestones")
    else:
        print(f"Milestones already exist ({len(existing_milestones)})")

    # ─── Buyers ───────────────────────────────────────────────────
    buyers_to_create = [
        {"email": "buyer1@test.com", "full_name": "Alice Buyer", "unit_number": "A101"},
        {"email": "buyer2@test.com", "full_name": "Bob Buyer", "unit_number": "B205"},
    ]

    for buyer_data in buyers_to_create:
        result = await db.execute(
            select(Buyer).where(
                Buyer.email == buyer_data["email"],
                Buyer.project_id == project.id,
            )
        )
        if not result.scalar_one_or_none():
            # Create buyer user
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
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(buyer_user)
                await db.flush()

            buyer = Buyer(
                id=new_id(),
                user_id=buyer_user.id,
                project_id=project.id,
                email=buyer_data["email"],
                full_name=buyer_data["full_name"],
                unit_number=buyer_data["unit_number"],
                invitation_sent_at=datetime.now(timezone.utc),
                registered_at=datetime.now(timezone.utc),
                notification_email=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(buyer)
            print(f"Created buyer: {buyer_data['email']}")
        else:
            print(f"Buyer already exists: {buyer_data['email']}")

    await db.flush()

    # ─── Test Upload ──────────────────────────────────────────────
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

        # Add placeholder photos
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
        print(f"Created test upload with 2 photos")
    else:
        print("Test upload already exists")

    await db.commit()
    print("\nSeed complete!")
    print(f"  Admin: admin@buildtrack.co.ke / Admin@2026!")
    print(f"  Developer: developer@acme.co.ke / Developer@2026!")
    print(f"  Buyers: buyer1@test.com, buyer2@test.com / Buyer@2026!")
    print(f"  Project code: SYCA01")


async def main():
    async with async_session_factory() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
