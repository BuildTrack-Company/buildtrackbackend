from pydantic import BaseModel, model_validator
from typing import Optional
from datetime import datetime


class DeveloperResponse(BaseModel):
    id: str
    user_id: str
    company_name: str
    contact_name: Optional[str] = None
    contact_person_name: Optional[str] = None
    subscription_tier: str
    subscription_status: str
    subscription_expires_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    years_operating: int = 0
    projects_completed: int = 0
    active_developments: int = 0
    avg_update_frequency_days: Optional[float] = None
    update_consistency_pct: Optional[float] = None
    company_overview: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    project_count: int = 0

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _fill_aliases(self) -> "DeveloperResponse":
        if not self.contact_person_name and self.contact_name:
            self.contact_person_name = self.contact_name
        return self


class DeveloperUpdate(BaseModel):
    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
