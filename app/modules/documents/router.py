from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.core.database import get_db
from app.core.deps import require_developer, require_admin, require_buyer
from app.core.exceptions import NotFoundError, ForbiddenError
from app.modules.auth.models import User
from app.modules.projects.models import Project
from app.modules.documents.models import ProjectDocument, DOCUMENT_TYPES
from app.shared.response import ok
from app.shared.ids import new_id
from app.shared.storage import get_signed_upload_params, get_document_download_url
from app.shared.audit import log_action

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["documents"])


class DocumentCreate(BaseModel):
    title: str
    document_type: str = "custom"
    cloudinary_public_id: str
    cloudinary_url: str
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    visible_to_buyers: bool = False

    @field_validator("document_type")
    @classmethod
    def _type(cls, v):
        if v not in DOCUMENT_TYPES:
            raise ValueError(f"document_type must be one of: {', '.join(DOCUMENT_TYPES)}")
        return v


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    document_type: Optional[str] = None
    visible_to_buyers: Optional[bool] = None


def _doc_format(mime_type: Optional[str]) -> str:
    """Cloudinary delivery format derived from the stored mime type."""
    m = (mime_type or "").lower()
    if "pdf" in m:
        return "pdf"
    if "png" in m:
        return "png"
    if "jpeg" in m or "jpg" in m:
        return "jpg"
    if m.startswith("image/"):
        return m.split("/", 1)[1]
    return "pdf"


def _serialize(d: ProjectDocument) -> dict:
    # Return an authenticated download URL (works even though Cloudinary blocks
    # plain PDF delivery) instead of the raw stored URL.
    download_url = (
        get_document_download_url(d.cloudinary_public_id, _doc_format(d.mime_type))
        if d.cloudinary_public_id else d.cloudinary_url
    )
    return {
        "id": d.id, "project_id": d.project_id, "title": d.title,
        "document_type": d.document_type,
        "cloudinary_url": download_url,
        "download_url": download_url,
        "cloudinary_public_id": d.cloudinary_public_id, "file_size_bytes": d.file_size_bytes,
        "mime_type": d.mime_type, "visible_to_buyers": d.visible_to_buyers,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


async def _owned_project(db, project_id, dev_id):
    p = (await db.execute(select(Project).where(
        Project.id == project_id, Project.developer_id == dev_id, Project.deleted_at.is_(None)
    ))).scalar_one_or_none()
    if not p:
        raise NotFoundError("Project not found")
    return p


@router.post("/projects/{project_id}/documents/sign")
async def sign_document_upload(project_id: str, request: Request,
                               current_user: User = Depends(require_developer), db: AsyncSession = Depends(get_db)):
    """Return signed Cloudinary params for a direct document upload."""
    from app.modules.developers import service as dev_service
    dev = await dev_service.get_developer_by_user_id(db, current_user.id)
    await _owned_project(db, project_id, dev.id)
    params = get_signed_upload_params(folder=f"documents/{project_id}", public_id_prefix=new_id())
    return ok(params, request=request)


@router.post("/projects/{project_id}/documents", status_code=201)
async def create_document(project_id: str, req: DocumentCreate, request: Request,
                          current_user: User = Depends(require_developer), db: AsyncSession = Depends(get_db)):
    from app.modules.developers import service as dev_service
    dev = await dev_service.get_developer_by_user_id(db, current_user.id)
    await _owned_project(db, project_id, dev.id)
    doc = ProjectDocument(
        id=new_id(), project_id=project_id, developer_id=dev.id, title=req.title,
        document_type=req.document_type, cloudinary_public_id=req.cloudinary_public_id,
        cloudinary_url=req.cloudinary_url, file_size_bytes=req.file_size_bytes,
        mime_type=req.mime_type, visible_to_buyers=req.visible_to_buyers,
        uploaded_by_user_id=current_user.id, created_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    await log_action(db, actor_user_id=current_user.id, actor_role="developer",
                     action="document.uploaded", entity_type="project_document", entity_id=doc.id,
                     developer_id=dev.id)
    return ok(_serialize(doc), request=request)


@router.get("/projects/{project_id}/documents")
async def list_documents(project_id: str, request: Request,
                         current_user: User = Depends(require_developer), db: AsyncSession = Depends(get_db)):
    from app.modules.developers import service as dev_service
    dev = await dev_service.get_developer_by_user_id(db, current_user.id)
    await _owned_project(db, project_id, dev.id)
    rows = (await db.execute(select(ProjectDocument).where(
        ProjectDocument.project_id == project_id, ProjectDocument.deleted_at.is_(None)
    ).order_by(ProjectDocument.created_at.desc()))).scalars().all()
    return ok([_serialize(d) for d in rows], request=request)


@router.patch("/projects/{project_id}/documents/{doc_id}")
async def update_document(project_id: str, doc_id: str, req: DocumentUpdate, request: Request,
                          current_user: User = Depends(require_developer), db: AsyncSession = Depends(get_db)):
    from app.modules.developers import service as dev_service
    dev = await dev_service.get_developer_by_user_id(db, current_user.id)
    doc = (await db.execute(select(ProjectDocument).where(
        ProjectDocument.id == doc_id, ProjectDocument.developer_id == dev.id, ProjectDocument.deleted_at.is_(None)
    ))).scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(doc, field, value)
    await db.commit()
    await db.refresh(doc)
    return ok(_serialize(doc), request=request)


@router.delete("/projects/{project_id}/documents/{doc_id}", status_code=204)
async def delete_document(project_id: str, doc_id: str, request: Request,
                          current_user: User = Depends(require_developer), db: AsyncSession = Depends(get_db)):
    from app.modules.developers import service as dev_service
    dev = await dev_service.get_developer_by_user_id(db, current_user.id)
    doc = (await db.execute(select(ProjectDocument).where(
        ProjectDocument.id == doc_id, ProjectDocument.developer_id == dev.id
    ))).scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")
    doc.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.get("/buyer/project/documents")
async def buyer_list_documents(request: Request,
                               current_user: User = Depends(require_buyer), db: AsyncSession = Depends(get_db)):
    from app.modules.buyers.models import Buyer
    buyer = (await db.execute(select(Buyer).where(Buyer.user_id == current_user.id, Buyer.deleted_at.is_(None)))).scalars().first()
    if not buyer:
        raise NotFoundError("No project associated with this buyer")
    rows = (await db.execute(select(ProjectDocument).where(
        ProjectDocument.project_id == buyer.project_id,
        ProjectDocument.visible_to_buyers == True,  # noqa: E712
        ProjectDocument.deleted_at.is_(None),
    ).order_by(ProjectDocument.created_at.desc()))).scalars().all()
    return ok([_serialize(d) for d in rows], request=request)


@router.get("/admin/projects/{project_id}/documents")
async def admin_list_documents(project_id: str, request: Request,
                               current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ProjectDocument).where(
        ProjectDocument.project_id == project_id, ProjectDocument.deleted_at.is_(None)
    ).order_by(ProjectDocument.created_at.desc()))).scalars().all()
    return ok([_serialize(d) for d in rows], request=request)
