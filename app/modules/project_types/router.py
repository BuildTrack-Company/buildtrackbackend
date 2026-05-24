from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.deps import require_admin, get_current_user
from app.modules.project_types import service
from app.shared.response import ok

router = APIRouter(prefix="/project-types", tags=["project-types"])


@router.get("")
async def list_project_types(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    data = await service.list_project_types(db)
    return ok(data)


@router.get("/templates")
async def list_workflow_templates(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    data = await service.list_workflow_templates(db)
    return ok(data)


@router.get("/templates/{template_id}")
async def get_workflow_template(template_id: str, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    data = await service.get_workflow_template(db, template_id)
    if not data:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Workflow template not found")
    return ok(data)
