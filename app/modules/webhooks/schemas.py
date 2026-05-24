from pydantic import BaseModel
from typing import Optional, Any


class WebhookPayload(BaseModel):
    type: Optional[str] = None
    data: Optional[Any] = None
