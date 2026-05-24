from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DeveloperResponse(BaseModel):
    id: str
    user_id: str
    company_name: str
    subscription_tier: str
    subscription_status: str
    subscription_expires_at: Optional[datetime]
    logo_url: Optional[str]
    website: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class DeveloperUpdate(BaseModel):
    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
