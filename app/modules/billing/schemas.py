from pydantic import BaseModel
from typing import Optional


class TierLimitsResponse(BaseModel):
    tier: str
    max_projects: int
    max_buyers_per_project: int
    max_photos_per_upload: int
    max_email_recipients_per_month: int
