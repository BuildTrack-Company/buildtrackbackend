import secrets
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.modules.members.models import DeveloperMember
from app.modules.auth.models import User
from app.modules.developers.models import Developer
from app.shared.ids import new_id
from app.core.security import hash_password
from app.core.exceptions import NotFoundError, DuplicateError, ForbiddenError, ValidationError


async def _send_member_invite_email(db: AsyncSession, developer_id: str, email: str, full_name: str, org_role: str, token: str):
    """Email a team invitation with the acceptance link. Awaited so it reliably
    sends (matches the buyer-invite pattern)."""
    from app.shared.email import send_email
    dev = (await db.execute(select(Developer).where(Developer.id == developer_id))).scalar_one_or_none()
    company = dev.company_name if dev else "your team"
    invite_link = f"https://buildtrack.co.ke/register/invite/{token}"
    try:
        await send_email(
            to=email,
            subject=f"You've been invited to join {company} on BuildTrack",
            html_body=(
                f"<p>Hello {full_name or 'there'},</p>"
                f"<p>You've been invited to join <strong>{company}</strong> on BuildTrack "
                f"as a <strong>{org_role}</strong>.</p>"
                f"<p>Click the link below to accept the invitation and set your password:</p>"
                f"<p><a href=\"{invite_link}\">{invite_link}</a></p>"
                f"<p>This invitation link expires in 7 days.</p>"
                f"<p>The BuildTrack Team</p>"
            ),
        )
    except Exception as e:  # best effort — don't fail the invite if email hiccups
        import logging
        logging.error(f"member invite email failed for {email}: {e}")


def _member_dict(m: DeveloperMember, u: Optional[User]) -> dict:
    return {
        "id": m.id,
        "developer_id": m.developer_id,
        "user_id": m.user_id,
        "email": u.email if u else m.invited_email,
        "full_name": u.full_name if u else None,
        "org_role": m.org_role,
        "invited_at": m.invited_at,
        "joined_at": m.joined_at,
        "is_active": m.is_active,
        "invitation_status": m.invitation_status,
    }


async def list_members(db: AsyncSession, developer_id: str) -> List[dict]:
    result = await db.execute(
        select(DeveloperMember, User)
        .outerjoin(User, User.id == DeveloperMember.user_id)
        .where(DeveloperMember.developer_id == developer_id, DeveloperMember.is_active == True)
        .order_by(DeveloperMember.invited_at)
    )
    return [_member_dict(m, u) for m, u in result.all()]


async def invite_member(db: AsyncSession, developer_id: str, email: str, full_name: str, org_role: str, invited_by: str) -> dict:
    if org_role not in ("owner", "admin", "member"):
        raise ValidationError("org_role must be owner, admin, or member")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if not user:
        temp_password = secrets.token_urlsafe(16)
        user = User(
            id=new_id(), email=email, hashed_password=hash_password(temp_password),
            role="developer", full_name=full_name, is_active=True, email_verified=False,
            created_at=now, updated_at=now,
        )
        db.add(user)
        await db.flush()

    existing = (await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.developer_id == developer_id,
            DeveloperMember.user_id == user.id,
        )
    )).scalar_one_or_none()
    if existing:
        raise DuplicateError("User is already a member of this organisation")

    member = DeveloperMember(
        id=new_id(), developer_id=developer_id, user_id=user.id, org_role=org_role,
        invited_by=invited_by, invited_at=now, is_active=True, invitation_status="active",
        joined_at=now, created_at=now,
    )
    db.add(member)
    await db.commit()
    return _member_dict(member, user)


async def invite_member_with_token(db: AsyncSession, developer_id: str, email: str, full_name: str, org_role: str, invited_by: str) -> dict:
    if org_role not in ("owner", "admin", "member"):
        raise ValidationError("org_role must be owner, admin, or member")

    # Check existing membership
    existing_user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing_user:
        existing_member = (await db.execute(
            select(DeveloperMember).where(
                DeveloperMember.developer_id == developer_id,
                DeveloperMember.user_id == existing_user.id,
                DeveloperMember.is_active == True,
            )
        )).scalar_one_or_none()
        if existing_member and existing_member.invitation_status == "active":
            raise DuplicateError("User is already an active member of this organisation")

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=7)

    member = DeveloperMember(
        id=new_id(),
        developer_id=developer_id,
        user_id=existing_user.id if existing_user else None,
        org_role=org_role,
        invited_by=invited_by,
        invited_at=now,
        is_active=True,
        invitation_status="pending",
        invitation_token=token,
        invitation_token_expires_at=expires_at,
        invited_email=email,
        created_at=now,
    )
    db.add(member)
    await db.commit()

    await _send_member_invite_email(db, developer_id, email, full_name, org_role, token)

    return {
        "id": member.id,
        "email": email,
        "invitation_status": "pending",
        "expires_at": expires_at.isoformat(),
    }


async def accept_invitation(db: AsyncSession, token: str, full_name: str, password: str) -> dict:
    member = (await db.execute(
        select(DeveloperMember).where(DeveloperMember.invitation_token == token)
    )).scalar_one_or_none()

    if not member:
        raise NotFoundError("Invitation not found or already used")
    if member.invitation_status == "revoked":
        raise ValidationError("This invitation has been revoked", {"code": "INVITATION_REVOKED"})
    if member.invitation_status != "pending":
        raise ValidationError("This invitation has already been accepted", {"code": "INVITATION_ALREADY_ACCEPTED"})
    if member.invitation_token_expires_at and datetime.now(timezone.utc) > member.invitation_token_expires_at:
        raise ValidationError("This invitation has expired", {"code": "INVITATION_EXPIRED"})

    now = datetime.now(timezone.utc)

    if member.user_id:
        user = (await db.execute(select(User).where(User.id == member.user_id))).scalar_one_or_none()
        if user:
            user.full_name = full_name
            user.hashed_password = hash_password(password)
    else:
        if not member.invited_email:
            raise ValidationError("Cannot accept invitation: email not found on invitation record", {"code": "MISSING_EMAIL"})
        user = User(
            id=new_id(), email=member.invited_email, hashed_password=hash_password(password),
            role="developer", full_name=full_name, is_active=True, email_verified=True,
            created_at=now, updated_at=now,
        )
        db.add(user)
        await db.flush()
        member.user_id = user.id

    member.invitation_status = "active"
    member.joined_at = now
    member.invitation_token = None
    member.invitation_token_expires_at = None

    await db.commit()
    return _member_dict(member, user)


async def update_member_status(db: AsyncSession, developer_id: str, member_id: str, invitation_status: str) -> dict:
    if invitation_status not in ("active", "suspended"):
        raise ValidationError("invitation_status must be 'active' or 'suspended'")

    result = await db.execute(
        select(DeveloperMember, User)
        .outerjoin(User, User.id == DeveloperMember.user_id)
        .where(DeveloperMember.id == member_id, DeveloperMember.developer_id == developer_id, DeveloperMember.is_active == True)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError("Member not found")

    member, user = row
    member.invitation_status = invitation_status
    await db.commit()
    return _member_dict(member, user)


async def remove_member(db: AsyncSession, developer_id: str, member_id: str, requester_id: str) -> None:
    result = await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.id == member_id, DeveloperMember.developer_id == developer_id,
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
        raise ValidationError("org_role must be owner, admin, or member")

    result = await db.execute(
        select(DeveloperMember, User)
        .outerjoin(User, User.id == DeveloperMember.user_id)
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
    return _member_dict(member, user)


async def resend_invitation(db: AsyncSession, developer_id: str, member_id: str) -> dict:
    member = (await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.id == member_id,
            DeveloperMember.developer_id == developer_id,
            DeveloperMember.is_active == True,
        )
    )).scalar_one_or_none()
    if not member:
        raise NotFoundError("Member not found")
    if member.invitation_status != "pending":
        raise ValidationError("Can only resend for pending invitations", {"code": "NOT_PENDING"})

    now = datetime.now(timezone.utc)
    member.invitation_token = secrets.token_urlsafe(32)
    member.invitation_token_expires_at = now + timedelta(days=7)
    await db.commit()

    # Resolve the invitee's name/email for the email.
    invitee = (await db.execute(select(User).where(User.id == member.user_id))).scalar_one_or_none() if member.user_id else None
    to_email = member.invited_email or (invitee.email if invitee else None)
    if to_email:
        await _send_member_invite_email(
            db, developer_id, to_email,
            (invitee.full_name if invitee else "") or "",
            member.org_role, member.invitation_token,
        )
    return {"member_id": member.id, "expires_at": member.invitation_token_expires_at}


async def revoke_invitation(db: AsyncSession, developer_id: str, member_id: str) -> None:
    member = (await db.execute(
        select(DeveloperMember).where(
            DeveloperMember.id == member_id,
            DeveloperMember.developer_id == developer_id,
            DeveloperMember.is_active == True,
        )
    )).scalar_one_or_none()
    if not member:
        raise NotFoundError("Member not found")
    if member.invitation_status != "pending":
        raise ValidationError("Can only revoke pending invitations", {"code": "NOT_PENDING"})
    member.invitation_status = "revoked"
    member.invitation_token = None
    member.invitation_token_expires_at = None
    await db.commit()
