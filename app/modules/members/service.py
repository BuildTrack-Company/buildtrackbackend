from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timezone
from app.modules.members.models import DeveloperMember
from app.modules.auth.models import User
from app.modules.developers.models import Developer
from app.shared.ids import new_id
from app.core.security import hash_password
from app.core.exceptions import NotFoundError, DuplicateError, ForbiddenError


async def list_members(db: AsyncSession, developer_id: str) -> List[dict]:
    result = await db.execute(
        select(DeveloperMember, User)
        .join(User, User.id == DeveloperMember.user_id)
        .where(DeveloperMember.developer_id == developer_id, DeveloperMember.is_active == True)
        .order_by(DeveloperMember.invited_at)
    )
    rows = result.all()
    return [
        {
            "id": m.id,
            "developer_id": m.developer_id,
            "user_id": m.user_id,
            "email": u.email,
            "full_name": u.full_name,
            "org_role": m.org_role,
            "invited_at": m.invited_at,
            "joined_at": m.joined_at,
            "is_active": m.is_active,
        }
        for m, u in rows
    ]


async def invite_member(db: AsyncSession, developer_id: str, email: str, full_name: str, org_role: str, invited_by: str) -> dict:
    if org_role not in ("owner", "admin", "member"):
        raise ValueError("org_role must be owner, admin, or member")

    # Check or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if not user:
        import secrets
        temp_password = secrets.token_urlsafe(16)
        user = User(
            id=new_id(),
            email=email,
            hashed_password=hash_password(temp_password),
            role="developer",
            full_name=full_name,
            is_active=True,
            email_verified=False,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.flush()

    # Check for existing membership
    existing = await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.developer_id == developer_id,
            DeveloperMember.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise DuplicateError("User is already a member of this organisation")

    member = DeveloperMember(
        id=new_id(),
        developer_id=developer_id,
        user_id=user.id,
        org_role=org_role,
        invited_by=invited_by,
        invited_at=now,
        is_active=True,
        created_at=now,
    )
    db.add(member)
    await db.commit()

    return {
        "id": member.id,
        "developer_id": developer_id,
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "org_role": org_role,
        "invited_at": now,
        "joined_at": None,
        "is_active": True,
    }


async def remove_member(db: AsyncSession, developer_id: str, member_id: str, requester_id: str) -> None:
    result = await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.id == member_id,
            DeveloperMember.developer_id == developer_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise NotFoundError("Member not found")
    if member.user_id == requester_id:
        raise ForbiddenError("Cannot remove yourself from the organisation")
    if member.org_role == "owner":
        raise ForbiddenError("Cannot remove the organisation owner")

    member.is_active = False
    await db.commit()


async def update_member_role(db: AsyncSession, developer_id: str, member_id: str, org_role: str) -> dict:
    if org_role not in ("owner", "admin", "member"):
        raise ValueError("org_role must be owner, admin, or member")

    result = await db.execute(
        select(DeveloperMember, User)
        .join(User, User.id == DeveloperMember.user_id)
        .where(
            DeveloperMember.id == member_id,
            DeveloperMember.developer_id == developer_id,
            DeveloperMember.is_active == True,
        )
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError("Member not found")

    member, user = row
    member.org_role = org_role
    await db.commit()

    return {
        "id": member.id,
        "developer_id": developer_id,
        "user_id": member.user_id,
        "email": user.email,
        "full_name": user.full_name,
        "org_role": org_role,
        "invited_at": member.invited_at,
        "joined_at": member.joined_at,
        "is_active": member.is_active,
    }
