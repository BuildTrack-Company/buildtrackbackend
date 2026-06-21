from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class BuyerInviteRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    unit_number: Optional[str] = None
    phone: Optional[str] = None


class BulkInviteRequest(BaseModel):
    buyers: List[BuyerInviteRequest]


class BuyerUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    unit_number: Optional[str] = None
    phone: Optional[str] = None
    notification_email: Optional[bool] = None


class BuyerResponse(BaseModel):
    id: str
    project_id: str
    email: str
    full_name: Optional[str]
    unit_number: Optional[str]
    phone: Optional[str]
    invitation_sent_at: Optional[datetime]
    registered_at: Optional[datetime]
    notification_email: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationPreferencesUpdate(BaseModel):
    notification_email: Optional[bool] = None
    notification_sms: Optional[bool] = None
    notification_whatsapp: Optional[bool] = None
