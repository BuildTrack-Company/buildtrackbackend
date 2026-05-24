from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class PermissionOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    resource: str
    action: str

    model_config = {"from_attributes": True}


class RoleOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    is_system: bool
    permissions: List[PermissionOut] = []

    model_config = {"from_attributes": True}


class UserRoleAssignmentOut(BaseModel):
    id: str
    user_id: str
    role_id: str
    role_name: str
    developer_id: Optional[str]
    granted_at: datetime
    expires_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AssignRoleRequest(BaseModel):
    user_id: str
    role_id: str
    expires_at: Optional[datetime] = None


class RoleCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    permission_ids: List[str] = []
