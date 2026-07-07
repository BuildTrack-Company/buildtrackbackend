from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class AuditLogResponse(BaseModel):
    id: str
    actor_user_id: Optional[str]
    actor_email: Optional[str] = None
    actor_role: Optional[str]
    action: str
    entity_type: str
    entity_id: str
    developer_id: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateDeveloperAdminRequest(BaseModel):
    email: EmailStr
    password: str
    contact_person_name: str
    company_name: str
    contact_phone: Optional[str] = None
    years_operating: int = 0
    projects_completed: int = 0
    active_developments: int = 0
    avg_update_frequency_days: Optional[float] = None
    update_consistency_pct: Optional[float] = None
    company_description: Optional[str] = None
    subscription_tier: str = "trial"


class SubscriptionUpdate(BaseModel):
    subscription_tier: Optional[str] = None
    subscription_status: Optional[str] = None


class UserAdminResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: str
    is_active: bool
    email_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # admin, developer, buyer
    phone: Optional[str] = None


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    email_verified: Optional[bool] = None


class SetUserPasswordRequest(BaseModel):
    password: str


class AdminUploadReview(BaseModel):
    action: str  # approve, reject
    reason: Optional[str] = None
    send_notification: bool = True
    title: Optional[str] = None


class PlatformStatsResponse(BaseModel):
    total_developers: int
    total_projects: int
    total_buyers: int
    total_uploads: int
    flagged_uploads: int


class AdminProjectCreate(BaseModel):
    developer_id: str
    project_code: str
    name: str
    location_name: Optional[str] = None
    site_latitude: Optional[float] = None
    site_longitude: Optional[float] = None
    gps_radius_metres: float = 100.0
    total_units: Optional[int] = None

