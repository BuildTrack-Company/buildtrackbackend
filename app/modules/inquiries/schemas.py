from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class InquiryCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = None
    location: Optional[str] = None
    message: Optional[str] = None
    source: str = "visibility_page"  # visibility_page, directory_card, home_page


class InquiryResponse(BaseModel):
    id: str
    project_id: str
    developer_id: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str]
    location: Optional[str]
    message: Optional[str]
    source: str
    seen_by_developer: bool
    seen_at: Optional[datetime]
    converted_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
