from pydantic import BaseModel
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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MilestoneUpdate(BaseModel):
    expected_date: Optional[datetime] = None
    description: Optional[str] = None


class MilestoneCompleteRequest(BaseModel):
    notes: Optional[str] = None


class MilestoneDelayRequest(BaseModel):
    reason: str
    new_expected_date: datetime
