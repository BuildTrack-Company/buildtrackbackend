from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ProjectCreate(BaseModel):
    name: str
    location_name: str
    site_latitude: float
    site_longitude: float
    total_units: int
    description: Optional[str] = None
    gps_radius_metres: float = 100.0
    estimated_completion: Optional[datetime] = None
    workflow_template_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    location_name: Optional[str] = None
    site_latitude: Optional[float] = None
    site_longitude: Optional[float] = None
    gps_radius_metres: Optional[float] = None
    total_units: Optional[int] = None
    status: Optional[str] = None
    estimated_completion: Optional[datetime] = None
    is_public: Optional[bool] = None


class ProjectResponse(BaseModel):
    id: str
    developer_id: str
    project_code: str
    name: str
    description: Optional[str]
    location_name: Optional[str]
    site_latitude: Optional[float]
    site_longitude: Optional[float]
    gps_radius_metres: float
    total_units: Optional[int]
    status: str
    cover_image_url: Optional[str]
    estimated_completion: Optional[datetime]
    is_public: bool
    slug: Optional[str] = None
    visibility_description: Optional[str] = None
    visibility_tagline: Optional[str] = None
    starting_price: Optional[str] = None
    construction_progress: int = 0
    health_status: str = "on_schedule"
    activity_overdue_threshold_days: int = 14
    visibility_page_views: int = 0
    visibility_page_published: bool = False
    project_type_id: Optional[str]
    workflow_template_id: Optional[str]
    current_stage_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
