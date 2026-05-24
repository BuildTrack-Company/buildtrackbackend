from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


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
    caption: Optional[str] = None
    capture_latitude: float
    capture_longitude: float
    accuracy_m: float
    photos: List[PhotoInput]


class UploadResponse(BaseModel):
    id: str
    project_id: str
    developer_id: str
    milestone_id: Optional[str]
    caption: Optional[str]
    capture_latitude: Optional[float]
    capture_longitude: Optional[float]
    accuracy_m: Optional[float]
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
