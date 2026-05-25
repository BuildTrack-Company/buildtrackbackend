from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.deps import require_admin, get_current_user, get_tenant_context, TenantContext, require_permission
from app.modules.roles import service
from app.modules.roles.schemas import AssignRoleRequest, RoleCreateRequest, RoleUpdateRequest, RolePermissionsRequest
from app.shared.response import ok
from app.modules.auth.models import User

router = APIRouter(tags=["roles"])


# IMPORTANT: register /roles/permissions BEFORE /roles/{role_id} to prevent shadowing
@router.get("/roles/permissions", dependencies=[require_permission("roles", "read")])
async def list_permissions(db: AsyncSession = Depends(get_db), _ctx: TenantContext = Depends(get_tenant_context)):
    return ok(await service.list_permissions(db))


@router.get("/roles", dependencies=[require_permission("roles", "read")])
async def list_roles(db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    return ok(await service.list_roles(db))


@router.post("/roles", status_code=201, dependencies=[require_permission("roles", "manage")])
async def create_role(req: RoleCreateRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    return ok(await service.create_role(db, req.name, req.description, req.permission_ids or [], ctx.user_id))


@router.patch("/roles/{role_id}", dependencies=[require_permission("roles", "manage")])
async def update_role(
    role_id: str,
    req: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    return ok(await service.update_role(db, role_id, req.name, req.description, is_admin=(ctx.role == "admin")))


@router.delete("/roles/{role_id}", status_code=204, dependencies=[require_permission("roles", "manage")])
async def delete_role(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    await service.delete_role(db, role_id, is_admin=(ctx.role == "admin"))


@router.put("/roles/{role_id}/permissions", dependencies=[require_permission("roles", "manage")])
async def set_role_permissions(
    role_id: str,
    req: RolePermissionsRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    return ok(await service.set_role_permissions(db, role_id, req.permissions, is_admin=(ctx.role == "admin")))


@router.post("/roles/assign", dependencies=[require_permission("roles", "manage")])
async def assign_role(req: AssignRoleRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    return ok(await service.assign_role(db, req.user_id, req.role_id, ctx.developer_id, ctx.user_id, req.expires_at))


@router.get("/roles/my-assignments")
async def my_role_assignments(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ok(await service.list_user_roles(db, current_user.id))


@router.get("/roles/assignments/{user_id}")
async def user_role_assignments(user_id: str, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    return ok(await service.list_user_roles(db, user_id))


@router.delete("/roles/assignments/{assignment_id}", dependencies=[require_permission("roles", "manage")])
async def revoke_role(assignment_id: str, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    await service.revoke_role(db, assignment_id, ctx.developer_id if ctx.role != "admin" else None)
    return ok({"revoked": True})
