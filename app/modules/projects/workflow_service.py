from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
import json

from app.modules.projects.models import Project
from app.modules.project_types.models import WorkflowTemplate, WorkflowStage, WorkflowTransition
from app.modules.milestones.models import Milestone, MilestoneApproval
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.shared.ids import new_id
from app.shared.audit import log_action


async def _load_project(db: AsyncSession, project_id: str, developer_id: Optional[str], user_id: str, role: str) -> Optional[Project]:
    if role == "admin":
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
    elif role == "developer":
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.developer_id == developer_id,
                Project.deleted_at.is_(None),
            )
        )
    else:
        from app.modules.buyers.models import Buyer
        buyer_check = await db.execute(
            select(Buyer).where(
                Buyer.user_id == user_id,
                Buyer.project_id == project_id,
            )
        )
        if not buyer_check.scalar_one_or_none():
            return None
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
    return result.scalar_one_or_none()


def _stage_dict(s: WorkflowStage) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "order_index": s.order_index,
        "expected_duration_days": s.expected_duration_days,
        "requires_buyer_approval": s.requires_buyer_approval,
    }


async def _load_template_data(db: AsyncSession, workflow_template_id: str):
    tmpl = (await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == workflow_template_id))).scalar_one_or_none()
    stages = (await db.execute(
        select(WorkflowStage).where(WorkflowStage.workflow_template_id == workflow_template_id).order_by(WorkflowStage.order_index)
    )).scalars().all()
    transitions = (await db.execute(
        select(WorkflowTransition).where(WorkflowTransition.workflow_template_id == workflow_template_id)
    )).scalars().all()
    return tmpl, stages, transitions


async def get_project_workflow(db: AsyncSession, project_id: str, developer_id: Optional[str], user_id: str, role: str) -> dict:
    project = await _load_project(db, project_id, developer_id, user_id, role)
    if not project:
        raise NotFoundError("Project not found")
    if not project.workflow_template_id:
        raise NotFoundError("Project has no workflow template assigned")

    template, stages, transitions = await _load_template_data(db, project.workflow_template_id)

    current_stage = None
    current_stage_index = None
    for i, s in enumerate(stages):
        if s.id == project.current_stage_id:
            current_stage = s
            current_stage_index = i
            break

    return {
        "project_id": project_id,
        "workflow_template": {
            "id": template.id,
            "name": template.name,
            "project_type_id": template.project_type_id,
        } if template else None,
        "current_stage": _stage_dict(current_stage) if current_stage else None,
        "current_stage_index": current_stage_index,
        "stages": [_stage_dict(s) for s in stages],
        "transitions": [
            {
                "id": t.id,
                "from_stage_id": t.from_stage_id,
                "to_stage_id": t.to_stage_id,
                "name": t.name,
                "condition_type": t.condition_type,
            }
            for t in transitions
        ],
    }


async def get_next_stages(db: AsyncSession, project_id: str, developer_id: Optional[str], user_id: str, role: str) -> List[dict]:
    project = await _load_project(db, project_id, developer_id, user_id, role)
    if not project:
        raise NotFoundError("Project not found")
    if not project.workflow_template_id:
        raise NotFoundError("Project has no workflow template assigned")

    transitions = (await db.execute(
        select(WorkflowTransition).where(
            WorkflowTransition.workflow_template_id == project.workflow_template_id,
            WorkflowTransition.from_stage_id == project.current_stage_id,
        )
    )).scalars().all()

    results = []
    for t in transitions:
        stage = (await db.execute(select(WorkflowStage).where(WorkflowStage.id == t.to_stage_id))).scalar_one_or_none()
        if not stage:
            continue
        blockers = []
        if t.condition_type == "approval":
            linked_milestone = (await db.execute(
                select(Milestone).where(
                    Milestone.project_id == project_id,
                    Milestone.workflow_stage_id == t.to_stage_id,
                )
            )).scalar_one_or_none()
            if linked_milestone:
                has_approval = (await db.execute(
                    select(MilestoneApproval).where(
                        MilestoneApproval.milestone_id == linked_milestone.id,
                        MilestoneApproval.decision == "approved",
                    )
                )).scalar_one_or_none()
                if not has_approval:
                    blockers.append("requires_buyer_approval: no approved record for this milestone")
        results.append({
            "stage": _stage_dict(stage),
            "transition": {"id": t.id, "condition_type": t.condition_type},
            "blockers": blockers,
        })
    return results


async def advance_workflow(
    db: AsyncSession,
    project_id: str,
    developer_id: Optional[str],
    user_id: str,
    role: str,
    to_stage_id: str,
    notes: Optional[str],
    idempotency_key: Optional[str],
    request_id: Optional[str],
) -> dict:
    if role not in ("developer", "admin"):
        raise ForbiddenError("Only Developers and Admins can advance workflow stages")

    project = await _load_project(db, project_id, developer_id, user_id, role)
    if not project:
        raise NotFoundError("Project not found")
    if not project.workflow_template_id:
        raise ValidationError("Project has no workflow template assigned")

    # Idempotency: if this key already produced a successful advance, return current state
    if idempotency_key:
        existing = await db.execute(
            text("""
                SELECT id FROM audit_log
                WHERE action = 'project.workflow.advanced'
                  AND entity_id = :project_id
                  AND after_state LIKE :ikey_pattern
                LIMIT 1
            """),
            {"project_id": project_id, "ikey_pattern": f'%"{idempotency_key}"%'},
        )
        if existing.fetchone():
            return await get_project_workflow(db, project_id, developer_id, user_id, role)

    # Validate transition
    transition = (await db.execute(
        select(WorkflowTransition).where(
            WorkflowTransition.workflow_template_id == project.workflow_template_id,
            WorkflowTransition.from_stage_id == project.current_stage_id,
            WorkflowTransition.to_stage_id == to_stage_id,
        )
    )).scalar_one_or_none()
    if not transition:
        raise ValidationError(
            "No valid transition exists from the current stage to the requested stage",
            {"code": "INVALID_TRANSITION", "from_stage_id": project.current_stage_id, "to_stage_id": to_stage_id},
        )

    target_stage = (await db.execute(
        select(WorkflowStage).where(
            WorkflowStage.id == to_stage_id,
            WorkflowStage.workflow_template_id == project.workflow_template_id,
        )
    )).scalar_one_or_none()
    if not target_stage:
        raise NotFoundError("Target stage not found in this workflow template")

    # Buyer approval gate
    if transition.condition_type == "approval":
        linked_milestone = (await db.execute(
            select(Milestone).where(
                Milestone.project_id == project_id,
                Milestone.workflow_stage_id == to_stage_id,
            )
        )).scalar_one_or_none()
        if linked_milestone:
            has_approval = (await db.execute(
                select(MilestoneApproval).where(
                    MilestoneApproval.milestone_id == linked_milestone.id,
                    MilestoneApproval.decision == "approved",
                )
            )).scalar_one_or_none()
            if not has_approval:
                raise ValidationError(
                    "Stage requires buyer approval before advancing",
                    {"code": "BUYER_APPROVAL_REQUIRED"},
                )

    old_stage_id = project.current_stage_id
    now = datetime.now(timezone.utc)

    # Mark old stage's milestone complete
    if old_stage_id:
        old_milestone = (await db.execute(
            select(Milestone).where(
                Milestone.project_id == project_id,
                Milestone.workflow_stage_id == old_stage_id,
            )
        )).scalar_one_or_none()
        if old_milestone and old_milestone.status not in ("complete", "completed"):
            old_milestone.status = "complete"
            old_milestone.completed_at = now

    # Mark new stage's milestone in_progress
    new_milestone = (await db.execute(
        select(Milestone).where(
            Milestone.project_id == project_id,
            Milestone.workflow_stage_id == to_stage_id,
        )
    )).scalar_one_or_none()
    if new_milestone and new_milestone.status == "pending":
        new_milestone.status = "in_progress"

    project.current_stage_id = to_stage_id
    project.updated_at = now

    await db.flush()

    await log_action(
        db,
        actor_user_id=user_id,
        actor_role=role,
        action="project.workflow.advanced",
        entity_type="project",
        entity_id=project_id,
        developer_id=project.developer_id,
        before={"stage_id": old_stage_id},
        after={"stage_id": to_stage_id, "notes": notes, "idempotency_key": idempotency_key},
        request_id=request_id,
    )

    return await get_project_workflow(db, project_id, developer_id, user_id, role)


async def get_workflow_history(
    db: AsyncSession,
    project_id: str,
    developer_id: Optional[str],
    user_id: str,
    role: str,
    page: int = 1,
    limit: int = 20,
) -> dict:
    project = await _load_project(db, project_id, developer_id, user_id, role)
    if not project:
        raise NotFoundError("Project not found")

    offset = (page - 1) * limit
    rows = (await db.execute(
        text("""
            SELECT id, actor_user_id, actor_role, action, before_state, after_state, created_at
            FROM audit_log
            WHERE action = 'project.workflow.advanced' AND entity_id = :project_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"project_id": project_id, "limit": limit, "offset": offset},
    )).fetchall()

    return {
        "project_id": project_id,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": str(r.id),
                "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
                "actor_role": r.actor_role,
                "before": json.loads(r.before_state) if r.before_state else None,
                "after": json.loads(r.after_state) if r.after_state else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
