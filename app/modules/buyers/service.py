import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.modules.buyers.models import Buyer
from app.modules.buyers.schemas import BuyerInviteRequest, BulkInviteRequest
from app.modules.projects.models import Project
from app.core.exceptions import NotFoundError, DuplicateError, ForbiddenError, ValidationError
from app.shared.ids import new_id
from app.shared.email import send_email
from app.shared.quotas import assert_can_invite_buyer

logger = structlog.get_logger(__name__)


async def invite_buyer(
    db: AsyncSession, project_id: str, developer_id: str, req: BuyerInviteRequest
) -> Buyer:
    """Invite a buyer to a project."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    await assert_can_invite_buyer(db, project_id)

    # Check for existing buyer
    result = await db.execute(
        select(Buyer).where(
            Buyer.project_id == project_id,
            Buyer.email == req.email.lower(),
            Buyer.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none():
        raise DuplicateError("Buyer already invited to this project")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    # Create (or reuse) a login account so the buyer can sign in directly with a
    # temporary password — no invitation link click required.
    from app.modules.auth.models import User
    from app.core.security import hash_password
    from app.shared.code_gen import generate_temp_password

    existing_user = (await db.execute(
        select(User).where(User.email == req.email.lower())
    )).scalar_one_or_none()

    temp_password = None
    if existing_user:
        user_id = existing_user.id
    else:
        temp_password = generate_temp_password()
        user = User(
            id=new_id(),
            email=req.email.lower(),
            hashed_password=hash_password(temp_password),
            role="buyer",
            full_name=req.full_name,
            phone=req.phone,
            is_active=True,
            email_verified=True,
        )
        db.add(user)
        await db.flush()
        user_id = user.id

    buyer = Buyer(
        id=new_id(),
        user_id=user_id,
        project_id=project_id,
        email=req.email.lower(),
        full_name=req.full_name,
        unit_number=req.unit_number,
        phone=req.phone,
        invitation_token_hash=token_hash,
        invitation_token_expires_at=expires_at,
        invitation_sent_at=datetime.now(timezone.utc),
    )
    db.add(buyer)
    await db.flush()
    await db.commit()

    # Get developer company name
    from app.modules.developers.models import Developer
    dev_result = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev = dev_result.scalar_one_or_none()
    company_name = dev.company_name if dev else "Your Developer"

    await send_email(
        to=buyer.email,
        subject=f"You Now Have Access to Track Construction Progress — {project.name}",
        template_name="buyer_invitation.html.j2",
        template_context={
            "first_name": buyer.full_name or "Buyer",
            "developer_name": company_name,
            "project_name": project.name,
            "project_url": f"https://buildtrack.co.ke/project/{project.project_code}",
            "portal_link": f"https://buildtrack.co.ke/register?token={token}",
            "login_url": "https://buildtrack.co.ke/login/buyer",
            "email": buyer.email,
            "temp_password": temp_password,
        },
    )

    return buyer


async def bulk_invite_buyers(
    db: AsyncSession, project_id: str, developer_id: str, req: BulkInviteRequest
) -> List[Buyer]:
    """Invite multiple buyers at once."""
    buyers = []
    errors = []
    for buyer_req in req.buyers:
        try:
            buyer = await invite_buyer(db, project_id, developer_id, buyer_req)
            buyers.append(buyer)
        except (DuplicateError, Exception) as e:
            errors.append({"email": buyer_req.email, "error": str(e)})

    if buyers:
        await _notify_buyers_added(db, project_id, developer_id, len(buyers))

    return buyers, errors


async def _notify_buyers_added(db: AsyncSession, project_id: str, developer_id: str, count: int):
    """Notify the developer (and platform admin) that buyers were added."""
    try:
        from app.modules.developers.models import Developer
        from app.modules.auth.models import User
        from app.core.config import settings

        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        dev = (await db.execute(select(Developer).where(Developer.id == developer_id))).scalar_one_or_none()
        dev_user = (await db.execute(select(User).where(User.id == dev.user_id))).scalar_one_or_none() if dev else None

        recipients = set()
        if dev_user and dev_user.email:
            recipients.add(dev_user.email)
        # Platform admin / company inbox copy
        recipients.add(settings.EMAIL_REPLY_TO or "support@buildtrack.co.ke")

        project_name = project.name if project else "your project"
        company = dev.company_name if dev else "Developer"
        for to in recipients:
            await send_email(
                to=to,
                subject=f"{count} buyer{'s' if count != 1 else ''} added to {project_name}",
                html_body=(
                    f"<p>{count} buyer{'s' if count != 1 else ''} {'were' if count != 1 else 'was'} just "
                    f"added to <strong>{project_name}</strong> ({company}). Each buyer received a portal "
                    f"login with a temporary password.</p>"
                    f"<p>Manage buyers from your BuildTrack portal.</p>"
                ),
            )
    except Exception as e:  # best effort
        logger.warning("notify_buyers_added_failed", error=str(e))


async def list_buyers(db: AsyncSession, project_id: str, developer_id: str) -> List[Buyer]:
    """List buyers for a project."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Project not found")

    result = await db.execute(
        select(Buyer).where(
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
        ).order_by(Buyer.created_at.desc())
    )
    return result.scalars().all()


async def resend_invitation(db: AsyncSession, buyer_id: str, project_id: str, developer_id: str) -> Buyer:
    """Resend invitation email to a buyer."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    result = await db.execute(
        select(Buyer).where(
            Buyer.id == buyer_id,
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
        )
    )
    buyer = result.scalar_one_or_none()
    if not buyer:
        raise NotFoundError("Buyer not found")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    buyer.invitation_token_hash = token_hash
    buyer.invitation_token_expires_at = expires_at
    buyer.invitation_sent_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(buyer)

    await send_email(
        to=buyer.email,
        subject=f"You Now Have Access to Track Construction Progress — {project.name}",
        template_name="buyer_invitation.html.j2",
        template_context={
            "first_name": buyer.full_name or "Buyer",
            "developer_name": "BuildTrack",
            "project_name": project.name,
            "project_url": f"https://buildtrack.co.ke/project/{project.project_code}",
            "portal_link": f"https://buildtrack.co.ke/register?token={token}",
        },
    )

    return buyer


async def remove_buyer(db: AsyncSession, buyer_id: str, project_id: str, developer_id: str):
    """Soft-delete a buyer."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Project not found")

    result = await db.execute(
        select(Buyer).where(
            Buyer.id == buyer_id,
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
        )
    )
    buyer = result.scalar_one_or_none()
    if not buyer:
        raise NotFoundError("Buyer not found")

    buyer.deleted_at = datetime.now(timezone.utc)
    await db.commit()


async def register_buyer_by_code(db: AsyncSession, req) -> "User":
    """Self-register as a buyer using a public project code (Method 2 onboarding)."""
    from app.modules.auth.models import User
    from app.core.security import hash_password

    result = await db.execute(
        select(Project).where(
            Project.project_code == req.project_code.upper(),
            Project.is_public.is_(True),
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found or not publicly accessible")

    email = req.email.lower()

    # Prevent duplicate registrations on the same project
    result = await db.execute(
        select(Buyer).where(
            Buyer.project_id == project.id,
            Buyer.email == email,
            Buyer.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none():
        raise DuplicateError("You are already registered on this project")

    # Create or reuse user account
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        if user.role != "buyer":
            raise ValidationError("This email is already registered with a different role")
    else:
        user = User(
            id=new_id(),
            email=email,
            hashed_password=hash_password(req.password),
            role="buyer",
            full_name=req.full_name,
            phone=req.phone,
            is_active=True,
            email_verified=False,
        )
        db.add(user)
        await db.flush()

    buyer = Buyer(
        id=new_id(),
        user_id=user.id,
        project_id=project.id,
        email=email,
        full_name=req.full_name,
        unit_number=req.unit_number,
        phone=req.phone,
        registered_at=datetime.now(timezone.utc),
        notification_email=True,
    )
    db.add(buyer)
    await db.commit()

    await send_email(
        to=email,
        subject=f"Your BuildTrack Access is Confirmed — {project.name}",
        template_name="buyer_self_registration.html.j2",
        template_context={
            "first_name": req.full_name,
            "project_name": project.name,
            "portal_link": f"https://buildtrack.co.ke/dashboard",
        },
    )

    return user


async def accept_invitation(db: AsyncSession, token: str, req) -> "User":
    """Accept a buyer invitation and create user account."""
    from app.modules.auth.models import User
    from app.core.security import hash_password
    from app.core.exceptions import ValidationError

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await db.execute(
        select(Buyer).where(
            Buyer.invitation_token_hash == token_hash,
            Buyer.invitation_token_expires_at > datetime.now(timezone.utc),
            Buyer.registered_at.is_(None),
            Buyer.deleted_at.is_(None),
        )
    )
    buyer = result.scalar_one_or_none()
    if not buyer:
        raise ValidationError("Invalid or expired invitation token")

    # Check if user already exists
    result = await db.execute(select(User).where(User.email == buyer.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        buyer.user_id = existing_user.id
        buyer.registered_at = datetime.now(timezone.utc)
        if req.full_name:
            buyer.full_name = req.full_name
        await db.commit()
        return existing_user

    user = User(
        id=new_id(),
        email=buyer.email,
        hashed_password=hash_password(req.password),
        role="buyer",
        full_name=req.full_name or buyer.full_name,
        phone=req.phone or buyer.phone,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()

    buyer.user_id = user.id
    buyer.registered_at = datetime.now(timezone.utc)
    if req.full_name:
        buyer.full_name = req.full_name

    await db.commit()
    return user
