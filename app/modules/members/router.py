from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.deps import require_developer, get_tenant_context, TenantContext
from app.modules.members import service
from app.modules.members.schemas import InviteMemberRequest, UpdateMemberRoleRequest
from app.shared.response import ok
from app.modules.auth.models import User

router = APIRouter(prefix="/developers/me/members", tags=["members"])


@router.get("")
async def list_members(db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Developer access required")
    return ok(await service.list_members(db, ctx.developer_id))


@router.post("")
async def invite_member(req: InviteMemberRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Developer access required")
    data = await service.invite_member(db, ctx.developer_id, req.email, req.full_name, req.org_role, ctx.user_id)
    return ok(data)


@router.patch("/{member_id}/role")
async def update_member_role(member_id: str, req: UpdateMemberRoleRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Developer access required")
    data = await service.update_member_role(db, ctx.developer_id, member_id, req.org_role)
    return ok(data)


@router.delete("/{member_id}")
async def remove_member(member_id: str, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Developer access required")
    await service.remove_member(db, ctx.developer_id, member_id, ctx.user_id)
    return ok({"removed": True})
