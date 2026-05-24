from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.modules.project_types.models import ProjectType, WorkflowTemplate, WorkflowStage


async def list_project_types(db: AsyncSession) -> List[dict]:
    result = await db.execute(select(ProjectType).order_by(ProjectType.name))
    types = result.scalars().all()
    out = []
    for pt in types:
        templates_result = await db.execute(
            select(WorkflowTemplate)
            .where(WorkflowTemplate.project_type_id == pt.id, WorkflowTemplate.is_active == True)
            .order_by(WorkflowTemplate.name)
        )
        templates = templates_result.scalars().all()
        templates_out = []
        for tmpl in templates:
            stages_result = await db.execute(
                select(WorkflowStage)
                .where(WorkflowStage.workflow_template_id == tmpl.id)
                .order_by(WorkflowStage.order_index)
            )
            stages = stages_result.scalars().all()
            templates_out.append({
                "id": tmpl.id,
                "project_type_id": tmpl.project_type_id,
                "name": tmpl.name,
                "description": tmpl.description,
                "is_system": tmpl.is_system,
                "is_active": tmpl.is_active,
                "stages": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "order_index": s.order_index,
                        "expected_duration_days": s.expected_duration_days,
                    }
                    for s in stages
                ],
            })
        out.append({
            "id": pt.id,
            "name": pt.name,
            "description": pt.description,
            "is_system": pt.is_system,
            "templates": templates_out,
        })
    return out


async def get_workflow_template(db: AsyncSession, template_id: str) -> Optional[dict]:
    result = await db.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.id == template_id)
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        return None
    stages_result = await db.execute(
        select(WorkflowStage)
        .where(WorkflowStage.workflow_template_id == tmpl.id)
        .order_by(WorkflowStage.order_index)
    )
    stages = stages_result.scalars().all()
    return {
        "id": tmpl.id,
        "project_type_id": tmpl.project_type_id,
        "name": tmpl.name,
        "description": tmpl.description,
        "is_system": tmpl.is_system,
        "is_active": tmpl.is_active,
        "stages": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "order_index": s.order_index,
                "expected_duration_days": s.expected_duration_days,
            }
            for s in stages
        ],
    }


async def list_workflow_templates(db: AsyncSession) -> List[dict]:
    result = await db.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active == True).order_by(WorkflowTemplate.name)
    )
    templates = result.scalars().all()
    out = []
    for tmpl in templates:
        stages_result = await db.execute(
            select(WorkflowStage)
            .where(WorkflowStage.workflow_template_id == tmpl.id)
            .order_by(WorkflowStage.order_index)
        )
        stages = stages_result.scalars().all()
        out.append({
            "id": tmpl.id,
            "project_type_id": tmpl.project_type_id,
            "name": tmpl.name,
            "description": tmpl.description,
            "is_system": tmpl.is_system,
            "is_active": tmpl.is_active,
            "stages": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "order_index": s.order_index,
                    "expected_duration_days": s.expected_duration_days,
                }
                for s in stages
            ],
        })
    return out
