from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.modules.developers.models import Developer
from app.shared.email import send_email
import asyncio
from app.modules.auth.models import User
from app.modules.projects.models import Project
from app.modules.buyers.models import Buyer
from app.modules.uploads.models import Upload
from app.core.exceptions import NotFoundError
from app.shared.ids import new_id
from app.core.security import hash_password


async def list_developers(db: AsyncSession, page: int = 1, limit: int = 20, search: str = None):
    offset = (page - 1) * limit
    conditions = [Developer.deleted_at.is_(None)]
    if search:
        conditions.append(Developer.company_name.ilike(f"%{search}%"))

    # Join User for email/phone + project count subquery
    proj_count_sq = (
        select(Project.developer_id, func.count(Project.id).label("project_count"))
        .where(Project.deleted_at.is_(None))
        .group_by(Project.developer_id)
        .subquery()
    )
    stmt = (
        select(Developer, User.email, User.phone, func.coalesce(proj_count_sq.c.project_count, 0))
        .outerjoin(User, User.id == Developer.user_id)
        .outerjoin(proj_count_sq, proj_count_sq.c.developer_id == Developer.id)
        .where(*conditions)
        .order_by(Developer.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    results = []
    for dev, email, phone, project_count in rows:
        d = dev
        d.__dict__["email"] = email
        d.__dict__["phone"] = phone
        d.__dict__["project_count"] = project_count or 0
        results.append(d)

    count = (await db.execute(
        select(func.count()).select_from(Developer).where(*conditions)
    )).scalar_one()
    return results, count


async def create_developer_admin(db: AsyncSession, req) -> Developer:
    from app.core.exceptions import DuplicateError

    result = await db.execute(select(User).where(User.email == req.email.lower()))
    if result.scalar_one_or_none():
        raise DuplicateError("Email already registered")

    user = User(
        id=new_id(),
        email=req.email.lower(),
        hashed_password=hash_password(req.password),
        role="developer",
        full_name=req.contact_person_name,
        phone=getattr(req, "contact_phone", None),
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()

    developer = Developer(
        id=new_id(),
        user_id=user.id,
        company_name=req.company_name,
        contact_name=req.contact_person_name,
        subscription_tier=req.subscription_tier,
        subscription_status="active",
        years_operating=getattr(req, "years_operating", 0),
        projects_completed=getattr(req, "projects_completed", 0),
        active_developments=getattr(req, "active_developments", 0),
        avg_update_frequency_days=getattr(req, "avg_update_frequency_days", None),
        update_consistency_pct=getattr(req, "update_consistency_pct", None),
        company_overview=getattr(req, "company_description", None),
    )
    db.add(developer)
    await db.flush()

    # Assign developer_owner role automatically
    from app.modules.roles.models import Role, UserRoleAssignment
    from datetime import datetime, timezone as _tz
    owner_role = (await db.execute(select(Role).where(Role.name == "developer_owner"))).scalar_one_or_none()
    if owner_role:
        db.add(UserRoleAssignment(
            id=new_id(),
            user_id=user.id,
            role_id=owner_role.id,
            developer_id=developer.id,
            granted_at=datetime.now(_tz.utc),
        ))

    await db.commit()
    await db.refresh(developer)

    # Send the welcome + credentials email. Awaited directly (not a fire-and-forget
    # background task) so it reliably sends on serverless hosts — an un-referenced
    # asyncio task can be garbage-collected or cancelled once the request returns.
    from app.modules.settings.service import is_notification_enabled
    welcome_enabled = await is_notification_enabled(db, "notify_developer_welcome")
    if welcome_enabled:
        try:
            await send_email(
                to=req.email.lower(),
                subject="Welcome to BuildTrack - Developer Account",
                template_name="developer_credentials.html.j2",
                template_context={
                    "full_name": req.contact_person_name,
                    "company_name": req.company_name,
                    "email": req.email.lower(),
                    "temporary_password": req.password,
                    "login_url": "https://buildtrack.co.ke/login/developer"
                }
            )
        except Exception as e:
            import logging
            logging.error(f"Failed to send developer credential email: {e}")

    return developer


async def update_developer_admin(db: AsyncSession, developer_id: str, updates: dict) -> Developer:
    result = await db.execute(
        select(Developer).where(Developer.id == developer_id, Developer.deleted_at.is_(None))
    )
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundError("Developer not found")

    field_map = {"company_description": "company_overview"}
    for field, value in updates.items():
        mapped = field_map.get(field, field)
        if hasattr(dev, mapped):
            setattr(dev, mapped, value)

    dev.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(dev)
    return dev


async def soft_delete_developer(db: AsyncSession, developer_id: str):
    result = await db.execute(
        select(Developer).where(Developer.id == developer_id)
    )
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundError("Developer not found")
    dev.deleted_at = datetime.now(timezone.utc)
    await db.commit()


async def get_platform_stats(db: AsyncSession) -> dict:
    # Single round-trip: 5 scalar subqueries in one statement (Neon RTT is the bottleneck).
    from sqlalchemy import text
    row = (await db.execute(text("""
        SELECT
          (SELECT count(*) FROM developers WHERE deleted_at IS NULL) AS total_developers,
          (SELECT count(*) FROM projects   WHERE deleted_at IS NULL) AS total_projects,
          (SELECT count(*) FROM buyers     WHERE deleted_at IS NULL) AS total_buyers,
          (SELECT count(*) FROM uploads)                             AS total_uploads,
          (SELECT count(*) FROM uploads WHERE status = 'flagged')    AS flagged_uploads,
          (SELECT count(*) FROM uploads WHERE status = 'pending')    AS pending_uploads
    """))).mappings().one()
    return {
        "total_developers": row["total_developers"],
        "total_projects": row["total_projects"],
        "total_buyers": row["total_buyers"],
        "total_uploads": row["total_uploads"],
        "flagged_uploads": row["flagged_uploads"],
        "pending_uploads": row["pending_uploads"],
    }


async def get_platform_analytics(db: AsyncSession) -> dict:
    """Breakdowns for the admin dashboard charts (uploads, project health, top projects)."""
    from sqlalchemy import text

    upload_rows = (await db.execute(text(
        "SELECT status, count(*) AS c FROM uploads GROUP BY status"
    ))).mappings().all()
    uploads_by_status = {r["status"]: r["c"] for r in upload_rows}

    health_rows = (await db.execute(text(
        "SELECT health_status, count(*) AS c FROM projects WHERE deleted_at IS NULL GROUP BY health_status"
    ))).mappings().all()
    projects_by_health = {r["health_status"]: r["c"] for r in health_rows}

    tier_rows = (await db.execute(text(
        "SELECT subscription_tier, count(*) AS c FROM developers WHERE deleted_at IS NULL GROUP BY subscription_tier"
    ))).mappings().all()
    developers_by_tier = {r["subscription_tier"]: r["c"] for r in tier_rows}

    top_rows = (await db.execute(text(
        """
        SELECT p.name AS name, count(b.id) AS buyers
        FROM projects p
        LEFT JOIN buyers b ON b.project_id = p.id AND b.deleted_at IS NULL
        WHERE p.deleted_at IS NULL
        GROUP BY p.id, p.name
        ORDER BY buyers DESC
        LIMIT 6
        """
    ))).mappings().all()
    top_projects_by_buyers = [{"name": r["name"], "buyers": r["buyers"]} for r in top_rows]

    # Approved uploads per day, last 14 days (activity trend)
    trend_rows = (await db.execute(text(
        """
        SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, count(*) AS c
        FROM uploads
        WHERE created_at >= now() - interval '14 days'
        GROUP BY day ORDER BY day
        """
    ))).mappings().all()
    uploads_trend = [{"day": r["day"], "count": r["c"]} for r in trend_rows]

    return {
        "uploads_by_status": uploads_by_status,
        "projects_by_health": projects_by_health,
        "developers_by_tier": developers_by_tier,
        "top_projects_by_buyers": top_projects_by_buyers,
        "uploads_trend": uploads_trend,
    }
