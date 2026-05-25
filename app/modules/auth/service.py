from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import hashlib
import secrets
import structlog

from app.modules.auth.models import User, AuthTokenDenyList, PasswordResetToken
from app.modules.auth.schemas import RegisterDeveloperRequest, LoginRequest
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.core.config import settings
from app.core.exceptions import DuplicateError, UnauthorizedError, NotFoundError, ValidationError
from app.shared.ids import new_id
from app.shared.email import send_email

logger = structlog.get_logger(__name__)


async def register_developer(db: AsyncSession, req: RegisterDeveloperRequest) -> User:
    """Register a new developer user."""
    # Check for duplicate email
    result = await db.execute(select(User).where(User.email == req.email.lower()))
    if result.scalar_one_or_none():
        raise DuplicateError("An account with this email already exists")

    user = User(
        id=new_id(),
        email=req.email.lower(),
        hashed_password=hash_password(req.password),
        role="developer",
        full_name=req.full_name,
        phone=req.phone,
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    await db.flush()

    # Create developer profile
    from app.modules.developers.models import Developer
    developer = Developer(
        id=new_id(),
        user_id=user.id,
        company_name=req.company_name,
        subscription_tier="trial",
        subscription_status="active",
    )
    db.add(developer)
    await db.flush()

    # Create DeveloperMember record for the owner so RBAC context is resolvable
    from app.modules.members.models import DeveloperMember
    owner_member = DeveloperMember(
        id=new_id(),
        developer_id=developer.id,
        user_id=user.id,
        org_role="owner",
        invited_by=user.id,
        invited_at=datetime.now(timezone.utc),
        joined_at=datetime.now(timezone.utc),
        is_active=True,
        invitation_status="active",
    )
    db.add(owner_member)
    await db.flush()

    await db.commit()

    # Send welcome email (non-blocking)
    await send_email(
        to=user.email,
        subject="Welcome to BuildTrack!",
        template_name="welcome_developer.html.j2",
        template_context={"full_name": user.full_name, "company_name": req.company_name},
    )

    return user


async def authenticate_user(db: AsyncSession, email: str, password: str, role: str) -> User:
    """Authenticate a user and verify role."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")

    if user.role != role:
        raise UnauthorizedError("Invalid credentials for this login endpoint")

    if not user.is_active:
        raise UnauthorizedError("Account is disabled. Please contact support.")

    return user


async def create_tokens(user: User) -> dict:
    """Create access and refresh tokens for a user."""
    token_data = {"sub": user.id, "email": user.email, "role": user.role}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> dict:
    """Rotate refresh token and return new tokens."""
    try:
        payload = decode_token(refresh_token)
    except ValueError:
        raise UnauthorizedError("Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid token type")

    jti = payload.get("jti")
    if jti:
        result = await db.execute(select(AuthTokenDenyList).where(AuthTokenDenyList.jti == jti))
        if result.scalar_one_or_none():
            raise UnauthorizedError("Token has been revoked")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or disabled")

    # Deny-list the old refresh token
    if jti:
        exp = payload.get("exp")
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else datetime.now(timezone.utc) + timedelta(days=1)
        deny_entry = AuthTokenDenyList(
            id=new_id(),
            jti=jti,
            user_id=user_id,
            expires_at=expires_at,
        )
        db.add(deny_entry)
        await db.commit()

    return await create_tokens(user)


async def logout_user(db: AsyncSession, refresh_token: str):
    """Deny-list the refresh token on logout."""
    try:
        payload = decode_token(refresh_token)
        jti = payload.get("jti")
        if jti:
            exp = payload.get("exp")
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else datetime.now(timezone.utc) + timedelta(days=1)
            deny_entry = AuthTokenDenyList(
                id=new_id(),
                jti=jti,
                user_id=payload.get("sub", ""),
                expires_at=expires_at,
            )
            db.add(deny_entry)
            await db.commit()
    except Exception as e:
        logger.warning("logout_token_error", error=str(e))


async def request_password_reset(db: AsyncSession, email: str):
    """Create and send password reset token."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()

    if not user:
        # Return silently to prevent email enumeration
        return

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    reset_token = PasswordResetToken(
        id=new_id(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_token)
    await db.commit()

    await send_email(
        to=user.email,
        subject="Reset your BuildTrack password",
        template_name="password_reset.html.j2",
        template_context={
            "full_name": user.full_name or user.email,
            "reset_token": token,
            "expires_minutes": 60,
        },
    )


async def confirm_password_reset(db: AsyncSession, token: str, new_password: str):
    """Verify token and update password."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    )
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        raise ValidationError("Invalid or expired reset token")

    result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    user.hashed_password = hash_password(new_password)
    user.updated_at = datetime.now(timezone.utc)
    reset_token.used_at = datetime.now(timezone.utc)
    await db.commit()
