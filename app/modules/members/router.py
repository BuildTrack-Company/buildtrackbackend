from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.deps import get_tenant_context, TenantContext, require_permission
from app.modules.members import service
from app.modules.members.schemas import (
    InviteMemberRequest, InviteWithTokenRequest,
    UpdateMemberRoleRequest, UpdateMemberStatusRequest,
)
from app.shared.response import ok
from app.core.exceptions import ForbiddenError

router = APIRouter(prefix="/developers/me/members", tags=["members"])


def _require_developer(ctx: TenantContext):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")


@router.get("", dependencies=[require_permission("team", "read")])
async def list_members(db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    return ok(await service.list_members(db, ctx.developer_id))


@router.post("", status_code=201, dependencies=[require_permission("team", "invite")])
async def add_member(req: InviteMemberRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    return ok(await service.invite_member(db, ctx.developer_id, req.email, req.full_name, req.org_role, ctx.user_id))


@router.post("/invite", status_code=201, dependencies=[require_permission("team", "invite")])
async def invite_member_with_token(req: InviteWithTokenRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    return ok(await service.invite_member_with_token(db, ctx.developer_id, req.email, req.full_name, req.org_role, ctx.user_id))


@router.patch("/{member_id}/role", dependencies=[require_permission("team", "manage")])
async def update_member_role(member_id: str, req: UpdateMemberRoleRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    return ok(await service.update_member_role(db, ctx.developer_id, member_id, req.org_role))


@router.patch("/{member_id}", dependencies=[require_permission("team", "manage")])
async def update_member_status(member_id: str, req: UpdateMemberStatusRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    return ok(await service.update_member_status(db, ctx.developer_id, member_id, req.invitation_status))


@router.post("/{member_id}/resend-invitation", dependencies=[require_permission("team", "invite")])
async def resend_invitation(member_id: str, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    return ok(await service.resend_invitation(db, ctx.developer_id, member_id))


@router.post("/{member_id}/revoke-invitation", status_code=204, dependencies=[require_permission("team", "manage")])
async def revoke_invitation(member_id: str, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    await service.revoke_invitation(db, ctx.developer_id, member_id)


@router.delete("/{member_id}", status_code=204, dependencies=[require_permission("team", "manage")])
async def remove_member(member_id: str, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    _require_developer(ctx)
    await service.remove_member(db, ctx.developer_id, member_id, ctx.user_id)
