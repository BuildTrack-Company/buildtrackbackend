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
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateDeveloperAdminRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    company_name: str
    subscription_tier: str = "trial"


class SubscriptionUpdate(BaseModel):
    subscription_tier: Optional[str] = None
    subscription_status: Optional[str] = None


class AdminUploadReview(BaseModel):
    action: str  # approve, reject
    reason: Optional[str] = None
    send_notification: bool = True


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

