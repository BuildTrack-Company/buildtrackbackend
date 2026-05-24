from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from app.core.database import get_db
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedError, ForbiddenError
from app.modules.auth.models import User
from dataclasses import dataclass

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise UnauthorizedError("No authentication token provided")

    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        raise UnauthorizedError("Invalid or expired token")

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")

    # Check deny list
    from app.modules.auth.models import AuthTokenDenyList
    jti = payload.get("jti")
    if jti:
        result = await db.execute(select(AuthTokenDenyList).where(AuthTokenDenyList.jti == jti))
        if result.scalar_one_or_none():
            raise UnauthorizedError("Token has been revoked")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")

    if not user.is_active:
        raise UnauthorizedError("User account is disabled")

    return user


async def require_developer(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "developer":
        raise ForbiddenError("Developer access required")
    return current_user


async def require_buyer(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "buyer":
        raise ForbiddenError("Buyer access required")
    return current_user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise ForbiddenError("Admin access required")
    return current_user


@dataclass
class TenantContext:
    user_id: str
    role: str
    developer_id: Optional[str]


async def get_tenant_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    developer_id = None
    if current_user.role == "developer":
        from app.modules.developers.models import Developer
        result = await db.execute(
            select(Developer).where(Developer.user_id == current_user.id)
        )
        dev = result.scalar_one_or_none()
        if dev:
            developer_id = dev.id

    return TenantContext(
        user_id=current_user.id,
        role=current_user.role,
        developer_id=developer_id,
    )
