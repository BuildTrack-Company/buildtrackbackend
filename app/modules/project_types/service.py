from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional

from app.modules.project_types.models import ProjectType, WorkflowTemplate, WorkflowStage, WorkflowTransition
from app.modules.projects.models import Project
from app.core.exceptions import NotFoundError, ForbiddenError, DuplicateError, ValidationError
from app.shared.ids import new_id


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _stage_dict(s: WorkflowStage) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "order_index": s.order_index,
        "expected_duration_days": s.expected_duration_days,
        "requires_buyer_approval": s.requires_buyer_approval,
        "requires_photo": s.requires_photo,
        "requires_file": s.requires_file,
    }


def _transition_dict(t: WorkflowTransition) -> dict:
    return {
        "id": t.id,
        "from_stage_id": t.from_stage_id,
        "to_stage_id": t.to_stage_id,
        "name": t.name,
        "condition_type": t.condition_type,
    }


async def _get_stages(db: AsyncSession, template_id: str) -> List[WorkflowStage]:
    return (await db.execute(
        select(WorkflowStage).where(WorkflowStage.workflow_template_id == template_id).order_by(WorkflowStage.order_index)
    )).scalars().all()


async def _get_transitions(db: AsyncSession, template_id: str) -> List[WorkflowTransition]:
    return (await db.execute(
        select(WorkflowTransition).where(WorkflowTransition.workflow_template_id == template_id)
    )).scalars().all()


def _template_dict(tmpl: WorkflowTemplate, stages: list, transitions: list = None) -> dict:
    d = {
        "id": tmpl.id,
        "project_type_id": tmpl.project_type_id,
        "name": tmpl.name,
        "description": tmpl.description,
        "is_system": tmpl.is_system,
        "is_active": tmpl.is_active,
        "developer_id": tmpl.developer_id,
        "stages": [_stage_dict(s) for s in stages],
    }
    if transitions is not None:
        d["transitions"] = [_transition_dict(t) for t in transitions]
    return d


async def _projects_using_template(db: AsyncSession, template_id: str) -> int:
    result = await db.execute(
        select(Project).where(Project.workflow_template_id == template_id, Project.deleted_at.is_(None))
    )
    return len(result.scalars().all())


async def _projects_using_project_type(db: AsyncSession, type_id: str) -> int:
    result = await db.execute(
        select(Project).where(Project.project_type_id == type_id, Project.deleted_at.is_(None))
    )
    return len(result.scalars().all())


# ─── Project Types ────────────────────────────────────────────────────────────

async def list_project_types(db: AsyncSession, developer_id: Optional[str] = None) -> List[dict]:
    query = select(ProjectType).order_by(ProjectType.name)
    result = await db.execute(query)
    types = result.scalars().all()
    out = []
    for pt in types:
        # Only show system types + own tenant types
        if not pt.is_system and developer_id and pt.developer_id != developer_id:
            continue
        templates = await _list_templates_for_type(db, pt.id, developer_id)
        out.append({
            "id": pt.id,
            "name": pt.name,
            "description": pt.description,
            "is_system": pt.is_system,
            "developer_id": pt.developer_id,
            "templates": templates,
        })
    return out


async def _list_templates_for_type(db: AsyncSession, project_type_id: str, developer_id: Optional[str]) -> List[dict]:
    result = await db.execute(
        select(WorkflowTemplate).where(
            WorkflowTemplate.project_type_id == project_type_id,
            WorkflowTemplate.is_active == True,
        ).order_by(WorkflowTemplate.name)
    )
    templates = result.scalars().all()
    out = []
    for tmpl in templates:
        if not tmpl.is_system and developer_id and tmpl.developer_id != developer_id:
            continue
        stages = await _get_stages(db, tmpl.id)
        out.append(_template_dict(tmpl, stages))
    return out


async def create_project_type(db: AsyncSession, developer_id: str, name: str, description: Optional[str]) -> dict:
    existing = (await db.execute(select(ProjectType).where(ProjectType.name == name))).scalar_one_or_none()
    if existing:
        raise DuplicateError(f"Project type '{name}' already exists")
    now = datetime.now(timezone.utc)
    pt = ProjectType(id=new_id(), name=name, description=description, is_system=False, developer_id=developer_id, created_at=now, updated_at=now)
    db.add(pt)
    await db.commit()
    return {"id": pt.id, "name": pt.name, "description": pt.description, "is_system": pt.is_system, "developer_id": pt.developer_id, "templates": []}


async def update_project_type(db: AsyncSession, type_id: str, developer_id: Optional[str], name: Optional[str], description: Optional[str], is_admin: bool = False) -> dict:
    pt = (await db.execute(select(ProjectType).where(ProjectType.id == type_id))).scalar_one_or_none()
    if not pt:
        raise NotFoundError("Project type not found")
    if pt.is_system and not is_admin:
        raise ForbiddenError("System project types are read-only for tenants")
    if not is_admin and pt.developer_id != developer_id:
        raise ForbiddenError("You can only edit your own project types")
    if name:
        pt.name = name
    if description is not None:
        pt.description = description
    pt.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": pt.id, "name": pt.name, "description": pt.description, "is_system": pt.is_system, "developer_id": pt.developer_id}


async def delete_project_type(db: AsyncSession, type_id: str, developer_id: Optional[str], is_admin: bool = False) -> None:
    pt = (await db.execute(select(ProjectType).where(ProjectType.id == type_id))).scalar_one_or_none()
    if not pt:
        raise NotFoundError("Project type not found")
    if pt.is_system and not is_admin:
        raise ForbiddenError("System project types cannot be deleted by tenants")
    if not is_admin and pt.developer_id != developer_id:
        raise ForbiddenError("You can only delete your own project types")
    if await _projects_using_project_type(db, type_id) > 0:
        raise ValidationError("Project type is in use by one or more projects", {"code": "TYPE_IN_USE"})
    await db.delete(pt)
    await db.commit()


# ─── Workflow Templates ───────────────────────────────────────────────────────

async def list_workflow_templates(db: AsyncSession, developer_id: Optional[str] = None, project_type_id: Optional[str] = None) -> List[dict]:
    query = select(WorkflowTemplate).where(WorkflowTemplate.is_active == True)
    if project_type_id:
        query = query.where(WorkflowTemplate.project_type_id == project_type_id)
    templates = (await db.execute(query.order_by(WorkflowTemplate.name))).scalars().all()
    out = []
    for tmpl in templates:
        if not tmpl.is_system and developer_id and tmpl.developer_id != developer_id:
            continue
        stages = await _get_stages(db, tmpl.id)
        transitions = await _get_transitions(db, tmpl.id)
        out.append(_template_dict(tmpl, stages, transitions))
    return out


async def get_workflow_template(db: AsyncSession, template_id: str, developer_id: Optional[str] = None) -> Optional[dict]:
    tmpl = (await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == template_id))).scalar_one_or_none()
    if not tmpl:
        return None
    if not tmpl.is_system and developer_id and tmpl.developer_id != developer_id:
        return None
    stages = await _get_stages(db, tmpl.id)
    transitions = await _get_transitions(db, tmpl.id)
    return _template_dict(tmpl, stages, transitions)


async def get_template_stages(db: AsyncSession, template_id: str, developer_id: Optional[str] = None) -> Optional[dict]:
    tmpl = (await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == template_id))).scalar_one_or_none()
    if not tmpl:
        return None
    if not tmpl.is_system and developer_id and tmpl.developer_id != developer_id:
        return None
    stages = await _get_stages(db, tmpl.id)
    return {"template_id": template_id, "stages": [_stage_dict(s) for s in stages]}


async def get_template_transitions(db: AsyncSession, template_id: str, developer_id: Optional[str] = None) -> Optional[dict]:
    tmpl = (await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == template_id))).scalar_one_or_none()
    if not tmpl:
        return None
    if not tmpl.is_system and developer_id and tmpl.developer_id != developer_id:
        return None
    transitions = await _get_transitions(db, tmpl.id)
    return {"template_id": template_id, "transitions": [_transition_dict(t) for t in transitions]}


async def get_default_template_for_type(db: AsyncSession, project_type_id: str, developer_id: Optional[str] = None) -> Optional[dict]:
    # First try system template for this type
    result = await db.execute(
        select(WorkflowTemplate).where(
            WorkflowTemplate.project_type_id == project_type_id,
            WorkflowTemplate.is_system == True,
            WorkflowTemplate.is_active == True,
        ).limit(1)
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        return None
    stages = await _get_stages(db, tmpl.id)
    transitions = await _get_transitions(db, tmpl.id)
    return _template_dict(tmpl, stages, transitions)


async def create_workflow_template(
    db: AsyncSession,
    developer_id: str,
    project_type_id: str,
    name: str,
    description: Optional[str],
    stages: list,
    transitions: list,
) -> dict:
    # Verify project type exists and is accessible
    pt = (await db.execute(select(ProjectType).where(ProjectType.id == project_type_id))).scalar_one_or_none()
    if not pt:
        raise NotFoundError("Project type not found")

    now = datetime.now(timezone.utc)
    tmpl = WorkflowTemplate(
        id=new_id(),
        project_type_id=project_type_id,
        name=name,
        description=description,
        is_system=False,
        is_active=True,
        developer_id=developer_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tmpl)
    await db.flush()

    created_stages = await _create_stages(db, tmpl.id, stages, now)
    await _create_transitions(db, tmpl.id, transitions, created_stages, now)
    await db.commit()

    return _template_dict(tmpl, await _get_stages(db, tmpl.id), await _get_transitions(db, tmpl.id))


async def _create_stages(db: AsyncSession, template_id: str, stages_data: list, now: datetime) -> dict:
    """Creates stages and returns mapping of input index -> stage id."""
    index_to_id = {}
    for i, s in enumerate(stages_data):
        stage = WorkflowStage(
            id=new_id(),
            workflow_template_id=template_id,
            name=s.get("name"),
            description=s.get("description"),
            order_index=s.get("order_index", i),
            expected_duration_days=s.get("expected_duration_days"),
            requires_buyer_approval=s.get("requires_buyer_approval", False),
            requires_photo=s.get("requires_photo", False),
            requires_file=s.get("requires_file", False),
            created_at=now,
        )
        db.add(stage)
        await db.flush()
        index_to_id[i] = stage.id
        # Also support referencing by provided temp id
        if "id" in s:
            index_to_id[s["id"]] = stage.id
    return index_to_id


async def _create_transitions(db: AsyncSession, template_id: str, transitions_data: list, stage_id_map: dict, now: datetime):
    for t in transitions_data:
        from_id = stage_id_map.get(t.get("from_stage_id")) if t.get("from_stage_id") is not None else None
        to_id = stage_id_map.get(t.get("to_stage_id"))
        if not to_id:
            continue
        db.add(WorkflowTransition(
            id=new_id(),
            workflow_template_id=template_id,
            from_stage_id=from_id,
            to_stage_id=to_id,
            name=t.get("name"),
            condition_type=t.get("condition_type"),
            created_at=now,
        ))


async def duplicate_workflow_template(db: AsyncSession, template_id: str, developer_id: str) -> dict:
    tmpl = (await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == template_id))).scalar_one_or_none()
    if not tmpl:
        raise NotFoundError("Workflow template not found")

    now = datetime.now(timezone.utc)
    new_tmpl = WorkflowTemplate(
        id=new_id(),
        project_type_id=tmpl.project_type_id,
        name=f"{tmpl.name} (Copy)",
        description=tmpl.description,
        is_system=False,
        is_active=True,
        developer_id=developer_id,
        created_at=now,
        updated_at=now,
    )
    db.add(new_tmpl)
    await db.flush()

    old_stages = await _get_stages(db, tmpl.id)
    old_transitions = await _get_transitions(db, tmpl.id)
    old_to_new = {}
    for s in old_stages:
        new_stage = WorkflowStage(
            id=new_id(),
            workflow_template_id=new_tmpl.id,
            name=s.name,
            description=s.description,
            order_index=s.order_index,
            expected_duration_days=s.expected_duration_days,
            requires_buyer_approval=s.requires_buyer_approval,
            requires_photo=s.requires_photo,
            requires_file=s.requires_file,
            created_at=now,
        )
        db.add(new_stage)
        await db.flush()
        old_to_new[s.id] = new_stage.id

    for t in old_transitions:
        db.add(WorkflowTransition(
            id=new_id(),
            workflow_template_id=new_tmpl.id,
            from_stage_id=old_to_new.get(t.from_stage_id) if t.from_stage_id else None,
            to_stage_id=old_to_new[t.to_stage_id],
            name=t.name,
            condition_type=t.condition_type,
            created_at=now,
        ))

    await db.commit()
    return _template_dict(new_tmpl, await _get_stages(db, new_tmpl.id), await _get_transitions(db, new_tmpl.id))


async def update_workflow_template(
    db: AsyncSession,
    template_id: str,
    developer_id: Optional[str],
    name: Optional[str],
    description: Optional[str],
    stages: Optional[list],
    transitions: Optional[list],
    is_admin: bool = False,
) -> dict:
    tmpl = (await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == template_id))).scalar_one_or_none()
    if not tmpl:
        raise NotFoundError("Workflow template not found")
    if tmpl.is_system and not is_admin:
        raise ForbiddenError("System workflow templates are read-only for tenants")
    if not is_admin and tmpl.developer_id != developer_id:
        raise ForbiddenError("You can only edit your own workflow templates")

    # Option C: refuse if any project uses it
    if await _projects_using_template(db, template_id) > 0:
        raise ValidationError(
            "Template is in use by one or more projects — clone it first, then edit the clone",
            {"code": "TEMPLATE_IN_USE"},
        )

    now = datetime.now(timezone.utc)
    if name:
        tmpl.name = name
    if description is not None:
        tmpl.description = description
    tmpl.updated_at = now

    if stages is not None:
        # Rebuild stages + transitions atomically
        await db.execute(delete(WorkflowTransition).where(WorkflowTransition.workflow_template_id == template_id))
        await db.execute(delete(WorkflowStage).where(WorkflowStage.workflow_template_id == template_id))
        await db.flush()
        created = await _create_stages(db, template_id, stages, now)
        if transitions:
            await _create_transitions(db, template_id, transitions or [], created, now)

    await db.commit()
    return _template_dict(tmpl, await _get_stages(db, tmpl.id), await _get_transitions(db, tmpl.id))


async def delete_workflow_template(db: AsyncSession, template_id: str, developer_id: Optional[str], is_admin: bool = False) -> None:
    tmpl = (await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == template_id))).scalar_one_or_none()
    if not tmpl:
        raise NotFoundError("Workflow template not found")
    if tmpl.is_system and not is_admin:
        raise ForbiddenError("System workflow templates cannot be deleted by tenants")
    if not is_admin and tmpl.developer_id != developer_id:
        raise ForbiddenError("You can only delete your own workflow templates")
    if await _projects_using_template(db, template_id) > 0:
        raise ValidationError("Template is in use by one or more projects", {"code": "TEMPLATE_IN_USE"})
    await db.execute(delete(WorkflowTransition).where(WorkflowTransition.workflow_template_id == template_id))
    await db.execute(delete(WorkflowStage).where(WorkflowStage.workflow_template_id == template_id))
    await db.delete(tmpl)
    await db.commit()
