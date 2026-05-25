from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class MemberOut(BaseModel):
    id: str
    developer_id: str
    user_id: Optional[str]
    email: Optional[str]
    full_name: Optional[str]
    org_role: str
    invited_at: datetime
    joined_at: Optional[datetime]
    is_active: bool
    invitation_status: str

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    full_name: str
    org_role: str = "member"


class InviteWithTokenRequest(BaseModel):
    email: EmailStr
    full_name: str
    org_role: str = "member"
    message: Optional[str] = None


class UpdateMemberRoleRequest(BaseModel):
    org_role: str


class UpdateMemberStatusRequest(BaseModel):
    invitation_status: str  # active | suspended


class AcceptInvitationRequest(BaseModel):
    full_name: str
    password: str
