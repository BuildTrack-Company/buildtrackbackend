import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.modules.buyers.models import Buyer, ProjectUnit
from app.modules.buyers.schemas import BuyerInviteRequest, BulkInviteRequest
from app.modules.projects.models import Project
from app.core.exceptions import NotFoundError, DuplicateError, ForbiddenError, ValidationError
from app.shared.ids import new_id
from app.shared.email import send_email
from app.shared.quotas import assert_can_invite_buyer

logger = structlog.get_logger(__name__)


def normalize_unit(value: str) -> str:
    """Normalise a unit number for matching: lower-case, alphanumerics only.
    So "A-204", "a 204" and "A204" all compare equal, while "A-204" and "204"
    stay distinct (they are genuinely different units)."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


async def _verify_project_owner(db: AsyncSession, project_id: str, developer_id: str) -> Project:
    project = (await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    return project


async def record_project_unit(db: AsyncSession, project_id: str, unit_number: str) -> None:
    """Idempotently record a project unit (dedup on the normalised form).
    Commit is left to the caller."""
    norm = normalize_unit(unit_number)
    if not norm:
        return
    existing = (await db.execute(
        select(ProjectUnit).where(
            ProjectUnit.project_id == project_id,
            ProjectUnit.unit_number_normalized == norm,
            ProjectUnit.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing:
        return
    db.add(ProjectUnit(
        id=new_id(),
        project_id=project_id,
        unit_number=unit_number.strip(),
        unit_number_normalized=norm,
    ))


async def add_project_unit(db: AsyncSession, project_id: str, developer_id: str, unit_number: str) -> dict:
    """Developer adds a single assigned unit (separate from the bulk CSV)."""
    await _verify_project_owner(db, project_id, developer_id)
    if not normalize_unit(unit_number):
        raise ValidationError("Enter a valid unit number")
    await record_project_unit(db, project_id, unit_number)
    await db.commit()
    return {"unit_number": unit_number.strip()}


async def list_project_units(db: AsyncSession, project_id: str, developer_id: str) -> List[dict]:
    """All assigned units for a project — the explicit project_units plus any unit
    numbers already present on buyer records — de-duplicated on the normalised form."""
    await _verify_project_owner(db, project_id, developer_id)
    seen: dict[str, dict] = {}

    rows = (await db.execute(
        select(ProjectUnit).where(
            ProjectUnit.project_id == project_id,
            ProjectUnit.deleted_at.is_(None),
        ).order_by(ProjectUnit.created_at)
    )).scalars().all()
    for u in rows:
        seen.setdefault(u.unit_number_normalized, {"id": u.id, "unit_number": u.unit_number, "source": "assigned"})

    buyers = (await db.execute(
        select(Buyer).where(
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
        )
    )).scalars().all()
    for b in buyers:
        norm = normalize_unit(b.unit_number or "")
        if norm and norm not in seen:
            seen[norm] = {"id": None, "unit_number": b.unit_number, "source": "buyer"}

    return list(seen.values())


async def delete_project_unit(db: AsyncSession, unit_id: str, project_id: str, developer_id: str) -> None:
    await _verify_project_owner(db, project_id, developer_id)
    unit = (await db.execute(
        select(ProjectUnit).where(ProjectUnit.id == unit_id, ProjectUnit.project_id == project_id)
    )).scalar_one_or_none()
    if not unit:
        raise NotFoundError("Unit not found")
    unit.deleted_at = datetime.now(timezone.utc)
    await db.commit()


async def _assigned_normalized_units(db: AsyncSession, project_id: str) -> set[str]:
    """Set of valid normalised unit numbers for a project (project_units ∪ buyers)."""
    units = set()
    rows = (await db.execute(
        select(ProjectUnit.unit_number_normalized).where(
            ProjectUnit.project_id == project_id,
            ProjectUnit.deleted_at.is_(None),
        )
    )).scalars().all()
    units.update(u for u in rows if u)
    buyer_units = (await db.execute(
        select(Buyer.unit_number).where(
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
        )
    )).scalars().all()
    units.update(normalize_unit(u) for u in buyer_units if normalize_unit(u or ""))
    return units


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
    # Register the buyer's unit as an assigned project unit so it validates
    # future self-registrations (e.g. co-owners on the same unit).
    if req.unit_number:
        await record_project_unit(db, project_id, req.unit_number)
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
            "portal_link": "https://buildtrack.co.ke/login/buyer",
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

    # Reset the buyer's login to a fresh temporary password so the resent email
    # always carries working credentials (they sign in directly at /login/buyer).
    from app.modules.auth.models import User
    from app.core.security import hash_password
    from app.shared.code_gen import generate_temp_password
    temp_password = generate_temp_password()
    user = (await db.execute(select(User).where(User.id == buyer.user_id))).scalar_one_or_none()
    if user:
        user.hashed_password = hash_password(temp_password)
        user.is_active = True
        user.email_verified = True
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
            "portal_link": "https://buildtrack.co.ke/login/buyer",
            "login_url": "https://buildtrack.co.ke/login/buyer",
            "email": buyer.email,
            "temp_password": temp_password,
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


async def update_buyer(db: AsyncSession, buyer_id: str, project_id: str, developer_id: str, req):
    """Update an existing buyer's editable fields (tenant-scoped)."""
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

    if req.full_name is not None:
        buyer.full_name = req.full_name
    if req.unit_number is not None:
        buyer.unit_number = req.unit_number
    if req.phone is not None:
        buyer.phone = req.phone
    if req.notification_email is not None:
        buyer.notification_email = req.notification_email
    buyer.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(buyer)
    return buyer


async def register_buyer_by_code(db: AsyncSession, req) -> "User":
    """Self-register as a buyer using a public project code (Method 2 onboarding)."""
    from app.modules.auth.models import User
    from app.core.security import hash_password

    result = await db.execute(
        select(Project).where(
            Project.project_code == req.project_code.upper(),
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Invalid project code")

    # Validate the buyer's unit number against the units the developer assigned
    # (bulk CSV + "Add Unit"), matched on the normalised form. Co-owners are
    # allowed and the unit stays open, so we only check that the unit exists.
    unit_input = normalize_unit(getattr(req, "unit_number", "") or "")
    if not unit_input:
        raise ValidationError("Your unit number is required to register")
    valid_units = await _assigned_normalized_units(db, project.id)
    if unit_input not in valid_units:
        raise ValidationError(
            "That unit number isn't recognised for this project. "
            "Please check with your developer that your unit has been added."
        )

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

    now = datetime.now(timezone.utc)
    buyer = Buyer(
        id=new_id(),
        user_id=user.id,
        project_id=project.id,
        email=email,
        full_name=req.full_name,
        unit_number=req.unit_number,
        phone=req.phone,
        location=getattr(req, "location", None),
        registered_at=now,
        last_active_at=now,
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
