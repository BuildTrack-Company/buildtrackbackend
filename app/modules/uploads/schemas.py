from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


# Predefined construction-update categories (brief Section 7 / visibility timeline)
UPLOAD_CATEGORIES = [
    "Foundation Works",
    "Structural Works",
    "Roofing Works",
    "Facade Works",
    "MEP Installation",
    "Finishing Works",
    "Milestone Completed",
    "General Update",
]


class UploadSessionRequest(BaseModel):
    project_id: str
    capture_latitude: float
    capture_longitude: float
    accuracy_m: float
    photo_count: int = 1
    milestone_id: Optional[str] = None


class UploadSessionResponse(BaseModel):
    session_id: str
    signing_params: List[dict]
    expires_at: datetime


class PhotoInput(BaseModel):
    cloudinary_public_id: str
    cloudinary_url: Optional[str] = None
    original_filename: Optional[str] = None
    capture_latitude: Optional[float] = None
    capture_longitude: Optional[float] = None
    accuracy_m: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size_bytes: Optional[int] = None
    order_index: int = 0


class FinalizeUploadRequest(BaseModel):
    session_id: str
    project_id: str
    milestone_id: Optional[str] = None
    title: str
    category: str
    progress_at_upload: int = Field(ge=0, le=100)
    # A written update is mandatory — enforce a non-empty caption at the API level.
    caption: str = Field(min_length=1)
    capture_latitude: float
    capture_longitude: float
    accuracy_m: float
    photos: List[PhotoInput]

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in UPLOAD_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(UPLOAD_CATEGORIES)}")
        return v


class UploadResponse(BaseModel):
    id: str
    project_id: str
    developer_id: str
    milestone_id: Optional[str]
    title: Optional[str] = None
    category: Optional[str] = None
    progress_at_upload: Optional[int] = None
    caption: Optional[str]
    capture_latitude: Optional[float]
    capture_longitude: Optional[float]
    accuracy_m: Optional[float]
    distance_from_site_m: Optional[float] = None
    within_boundary: bool = False
    gps_validated: bool
    photo_count: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PhotoResponse(BaseModel):
    id: str
    upload_id: str
    cloudinary_public_id: str
    cloudinary_url: Optional[str]
    original_filename: Optional[str]
    order_index: int
    signed_url: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
