from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.deps import require_admin, require_developer, get_current_user, get_tenant_context, TenantContext
from app.modules.roles import service
from app.modules.roles.schemas import AssignRoleRequest, RoleCreateRequest
from app.shared.response import ok
from app.modules.auth.models import User

router = APIRouter(tags=["roles"])


@router.get("/roles")
async def list_roles(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    return ok(await service.list_roles(db))


@router.get("/permissions")
async def list_permissions(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    return ok(await service.list_permissions(db))


@router.post("/roles")
async def create_role(req: RoleCreateRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    data = await service.create_role(db, req.name, req.description, req.permission_ids, current_user.id)
    return ok(data)


@router.post("/roles/assign")
async def assign_role(req: AssignRoleRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    data = await service.assign_role(db, req.user_id, req.role_id, ctx.developer_id, ctx.user_id, req.expires_at)
    return ok(data)


@router.get("/roles/my-assignments")
async def my_role_assignments(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    data = await service.list_user_roles(db, current_user.id)
    return ok(data)


@router.get("/roles/assignments/{user_id}")
async def user_role_assignments(user_id: str, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    data = await service.list_user_roles(db, user_id)
    return ok(data)


@router.delete("/roles/assignments/{assignment_id}")
async def revoke_role(assignment_id: str, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    await service.revoke_role(db, assignment_id, ctx.developer_id if ctx.role != "admin" else None)
    return ok({"revoked": True})
