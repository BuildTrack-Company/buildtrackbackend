from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class WorkflowStageOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    order_index: int
    expected_duration_days: Optional[int]
    requires_buyer_approval: bool = False
    requires_photo: bool = False
    requires_file: bool = False

    model_config = {"from_attributes": True}


class WorkflowTemplateOut(BaseModel):
    id: str
    project_type_id: str
    name: str
    description: Optional[str]
    is_system: bool
    is_active: bool
    stages: List[WorkflowStageOut] = []

    model_config = {"from_attributes": True}


class ProjectTypeOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    is_system: bool
    templates: List[WorkflowTemplateOut] = []

    model_config = {"from_attributes": True}


class WorkflowTemplateCreateRequest(BaseModel):
    project_type_id: str
    name: str
    description: Optional[str] = None
    stages: List[dict]


class ProjectTypeCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
