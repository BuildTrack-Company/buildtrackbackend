from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class SettingOut(BaseModel):
    key: str
    value: Optional[str]
    updated_at: datetime

    model_config = {"from_attributes": True}


class SystemSettingOut(BaseModel):
    key: str
    value: Optional[str]
    description: Optional[str]
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateSettingRequest(BaseModel):
    value: Optional[str]


class BulkUpdateSettingsRequest(BaseModel):
    settings: List[UpdateSettingRequest]
    keys: List[str]
