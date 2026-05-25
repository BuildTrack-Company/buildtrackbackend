from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from app.core.database import get_db
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedError, ForbiddenError
from app.modules.auth.models import User
from dataclasses import dataclass, field

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
    org_role: Optional[str] = field(default=None)       # owner / admin / member (from DeveloperMember)
    is_primary_developer: bool = field(default=False)   # True = this user created the org (Developer.user_id)


async def get_tenant_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    developer_id = None
    org_role = None
    is_primary_developer = False

    if current_user.role == "developer":
        from app.modules.developers.models import Developer
        dev = (await db.execute(
            select(Developer).where(Developer.user_id == current_user.id)
        )).scalar_one_or_none()

        if dev:
            # This user IS the primary developer (account creator)
            developer_id = dev.id
            is_primary_developer = True
        else:
            # Team member — look up their DeveloperMember record
            from app.modules.members.models import DeveloperMember
            member = (await db.execute(
                select(DeveloperMember).where(
                    DeveloperMember.user_id == current_user.id,
                    DeveloperMember.is_active == True,
                    DeveloperMember.invitation_status == "active",
                ).order_by(DeveloperMember.joined_at.desc())
            )).scalars().first()

            if member:
                developer_id = member.developer_id
                org_role = member.org_role

    return TenantContext(
        user_id=current_user.id,
        role=current_user.role,
        developer_id=developer_id,
        org_role=org_role,
        is_primary_developer=is_primary_developer,
    )


async def _check_permission(
    db: AsyncSession,
    ctx: TenantContext,
    resource: str,
    action: str,
) -> None:
    """
    Permission check logic:
      - Platform admin → always allowed
      - Primary developer (org creator) → always allowed
      - Org owner or admin → always allowed
      - Org member → must have the specific permission via a role assignment
    """
    # Platform admin bypasses everything
    if ctx.role == "admin":
        return

    # Primary developer (account creator) bypasses RBAC
    if ctx.is_primary_developer:
        return

    # Org owners and admins bypass RBAC within their own org
    if ctx.org_role in ("owner", "admin"):
        return

    # No developer context at all → deny
    if not ctx.developer_id:
        raise ForbiddenError("No developer organisation context found")

    # Check custom RBAC roles for this user in this developer's org
    from app.modules.roles.models import Permission, RolePermission, UserRoleAssignment
    result = await db.execute(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
        .where(
            UserRoleAssignment.user_id == ctx.user_id,
            UserRoleAssignment.developer_id == ctx.developer_id,
            Permission.resource == resource,
            Permission.action == action,
        )
    )
    if not result.scalar_one_or_none():
        raise ForbiddenError(
            f"You do not have permission to perform this action ({resource}:{action}). "
            "Contact your organisation administrator."
        )


def require_permission(resource: str, action: str):
    """
    Dependency factory. Returns a FastAPI Depends that enforces RBAC.

    Usage in a route:
        @router.post("/projects", dependencies=[require_permission("projects", "create")])

    Or as a parameter when you want to also use the context:
        async def my_route(ctx: TenantContext = Depends(get_tenant_context), _=require_permission("projects", "create")):
    """
    async def _dep(
        ctx: TenantContext = Depends(get_tenant_context),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        await _check_permission(db, ctx, resource, action)

    return Depends(_dep)
