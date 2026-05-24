from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class MemberOut(BaseModel):
    id: str
    developer_id: str
    user_id: str
    email: str
    full_name: Optional[str]
    org_role: str
    invited_at: datetime
    joined_at: Optional[datetime]
    is_active: bool

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    full_name: str
    org_role: str = "member"


class UpdateMemberRoleRequest(BaseModel):
    org_role: str
