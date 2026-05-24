from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NotificationLogResponse(BaseModel):
    id: str
    upload_id: Optional[str]
    buyer_id: Optional[str]
    notification_type: str
    recipient_email: Optional[str]
    subject: Optional[str]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
