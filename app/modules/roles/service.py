from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional
from datetime import datetime, timezone
from app.modules.roles.models import Permission, Role, RolePermission, UserRoleAssignment
from app.modules.auth.models import User
from app.shared.ids import new_id
from app.core.exceptions import NotFoundError, DuplicateError, ForbiddenError, ValidationError


async def list_roles(db: AsyncSession) -> List[dict]:
    result = await db.execute(select(Role).order_by(Role.name))
    roles = result.scalars().all()
    out = []
    for role in roles:
        perms = await _get_role_permissions(db, role.id)
        out.append({
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permissions": perms,
        })
    return out


async def _get_role_permissions(db: AsyncSession, role_id: str) -> List[dict]:
    result = await db.execute(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.resource, Permission.action)
    )
    perms = result.scalars().all()
    return [
        {"id": p.id, "name": p.name, "description": p.description, "resource": p.resource, "action": p.action}
        for p in perms
    ]


async def list_permissions(db: AsyncSession) -> List[dict]:
    result = await db.execute(select(Permission).order_by(Permission.resource, Permission.action))
    perms = result.scalars().all()
    return [
        {"id": p.id, "name": p.name, "description": p.description, "resource": p.resource, "action": p.action}
        for p in perms
    ]


async def create_role(db: AsyncSession, name: str, description: Optional[str], permission_ids: List[str], granted_by: str) -> dict:
    existing = await db.execute(select(Role).where(Role.name == name))
    if existing.scalar_one_or_none():
        raise DuplicateError(f"Role '{name}' already exists")

    now = datetime.now(timezone.utc)
    role = Role(id=new_id(), name=name, description=description, is_system=False, created_at=now, updated_at=now)
    db.add(role)
    await db.flush()

    for perm_id in permission_ids:
        db.add(RolePermission(id=new_id(), role_id=role.id, permission_id=perm_id, created_at=now))
    await db.commit()

    perms = await _get_role_permissions(db, role.id)
    return {"id": role.id, "name": role.name, "description": role.description, "is_system": role.is_system, "permissions": perms}


async def update_role(db: AsyncSession, role_id: str, name: Optional[str], description: Optional[str], is_admin: bool = False) -> dict:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise NotFoundError("Role not found")
    if role.is_system and not is_admin:
        raise ForbiddenError("System roles are immutable for tenants")
    now = datetime.now(timezone.utc)
    if name is not None:
        role.name = name
    if description is not None:
        role.description = description
    role.updated_at = now
    await db.commit()
    perms = await _get_role_permissions(db, role.id)
    return {"id": role.id, "name": role.name, "description": role.description, "is_system": role.is_system, "permissions": perms}


async def delete_role(db: AsyncSession, role_id: str, is_admin: bool = False) -> None:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise NotFoundError("Role not found")
    if role.is_system and not is_admin:
        raise ForbiddenError("System roles cannot be deleted by tenants")
    # Check for active assignments
    assignments = (await db.execute(select(UserRoleAssignment).where(UserRoleAssignment.role_id == role_id))).scalars().all()
    if assignments:
        raise ValidationError(
            "Role is still assigned to one or more users — revoke all assignments first",
            {"code": "ROLE_IN_USE"},
        )
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    await db.delete(role)
    await db.commit()


async def set_role_permissions(db: AsyncSession, role_id: str, permission_ids: List[str], is_admin: bool = False) -> dict:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise NotFoundError("Role not found")
    if role.is_system and not is_admin:
        raise ForbiddenError("System role permissions are immutable for tenants")

    now = datetime.now(timezone.utc)
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    await db.flush()

    for perm_id in permission_ids:
        perm = (await db.execute(select(Permission).where(Permission.id == perm_id))).scalar_one_or_none()
        if not perm:
            raise NotFoundError(f"Permission '{perm_id}' not found")
        db.add(RolePermission(id=new_id(), role_id=role_id, permission_id=perm_id, created_at=now))

    await db.commit()
    perms = await _get_role_permissions(db, role_id)
    return {"id": role.id, "name": role.name, "description": role.description, "is_system": role.is_system, "permissions": perms}


async def assign_role(db: AsyncSession, user_id: str, role_id: str, developer_id: Optional[str], granted_by: str, expires_at) -> dict:
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    role_result = await db.execute(select(Role).where(Role.id == role_id))
    role = role_result.scalar_one_or_none()
    if not role:
        raise NotFoundError("Role not found")

    existing = await db.execute(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.role_id == role_id,
            UserRoleAssignment.developer_id == developer_id,
        )
    )
    if existing.scalar_one_or_none():
        raise DuplicateError("User already has this role assignment")

    now = datetime.now(timezone.utc)
    assignment = UserRoleAssignment(
        id=new_id(), user_id=user_id, role_id=role_id, developer_id=developer_id,
        granted_by=granted_by, granted_at=now, expires_at=expires_at, created_at=now,
    )
    db.add(assignment)
    await db.commit()

    return {
        "id": assignment.id,
        "user_id": user_id,
        "role_id": role_id,
        "role_name": role.name,
        "developer_id": developer_id,
        "granted_at": now,
        "expires_at": expires_at,
    }


async def list_user_roles(db: AsyncSession, user_id: str, developer_id: Optional[str] = None) -> List[dict]:
    query = select(UserRoleAssignment, Role).join(Role, Role.id == UserRoleAssignment.role_id).where(
        UserRoleAssignment.user_id == user_id
    )
    if developer_id:
        query = query.where(UserRoleAssignment.developer_id == developer_id)
    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "role_id": a.role_id,
            "role_name": r.name,
            "developer_id": a.developer_id,
            "granted_at": a.granted_at,
            "expires_at": a.expires_at,
        }
        for a, r in rows
    ]


async def revoke_role(db: AsyncSession, assignment_id: str, developer_id: Optional[str]) -> None:
    result = await db.execute(select(UserRoleAssignment).where(UserRoleAssignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise NotFoundError("Role assignment not found")
    if developer_id and assignment.developer_id != developer_id:
        raise NotFoundError("Role assignment not found")
    await db.delete(assignment)
    await db.commit()


async def user_has_permission(db: AsyncSession, user_id: str, resource: str, action: str, developer_id: Optional[str] = None) -> bool:
    result = await db.execute(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
        .where(
            UserRoleAssignment.user_id == user_id,
            Permission.resource == resource,
            Permission.action == action,
        )
    )
    return result.scalar_one_or_none() is not None
