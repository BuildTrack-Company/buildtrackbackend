from pydantic import BaseModel, model_validator
from typing import Optional
from datetime import datetime


class MilestoneResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str]
    order_index: int
    status: str
    expected_date: Optional[datetime]
    completed_at: Optional[datetime]
    delay_reason: Optional[str]
    delay_new_date: Optional[datetime]
    expected_date_set_at: Optional[datetime] = None
    date_locked: bool = False
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _compute_date_locked(self) -> "MilestoneResponse":
        from datetime import datetime, timezone
        if self.expected_date_set_at:
            age = (datetime.now(timezone.utc) - self.expected_date_set_at).total_seconds()
            self.date_locked = age > 48 * 3600
        return self

    model_config = {"from_attributes": True}


class MilestoneUpdate(BaseModel):
    expected_date: Optional[datetime] = None
    description: Optional[str] = None


class MilestoneCompleteRequest(BaseModel):
    notes: Optional[str] = None


class MilestoneDelayRequest(BaseModel):
    reason: str
    new_expected_date: datetime
