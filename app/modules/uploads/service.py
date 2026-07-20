from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.modules.uploads.models import Upload, Photo, UploadSession
from app.modules.uploads.schemas import (
    UploadSessionRequest, FinalizeUploadRequest, UploadSessionResponse
)
from app.modules.projects.models import Project
from app.core.exceptions import GPSRejectedError, NotFoundError, DuplicateError, ForbiddenError
from app.shared.ids import new_id
from app.shared.geo import haversine_metres
from app.shared.storage import get_signed_upload_params, get_signed_url
from app.shared.quotas import assert_can_upload_photos
from app.shared.audit import log_action

logger = structlog.get_logger(__name__)

GPS_ACCURACY_THRESHOLD = 100  # max accuracy in metres
GPS_DISTANCE_BUFFER = 20  # extra metres buffer beyond project radius


async def create_upload_session(
    db: AsyncSession, developer_id: str, req: UploadSessionRequest
) -> dict:
    """Validate GPS and return Cloudinary signing params."""
    # Check accuracy threshold
    if req.accuracy_m > GPS_ACCURACY_THRESHOLD:
        raise GPSRejectedError(
            f"GPS accuracy too low: {req.accuracy_m}m (max {GPS_ACCURACY_THRESHOLD}m)",
            {"accuracy_m": req.accuracy_m, "threshold": GPS_ACCURACY_THRESHOLD},
        )

    # Load project and verify ownership
    result = await db.execute(
        select(Project).where(
            Project.id == req.project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    # Check GPS distance from site
    if project.site_latitude and project.site_longitude:
        distance = haversine_metres(
            req.capture_latitude, req.capture_longitude,
            project.site_latitude, project.site_longitude,
        )
        allowed_radius = project.gps_radius_metres + GPS_DISTANCE_BUFFER
        if distance > allowed_radius:
            raise GPSRejectedError(
                f"Location too far from project site: {distance:.0f}m (allowed: {allowed_radius:.0f}m)",
                {
                    "distance_m": round(distance),
                    "allowed_radius_m": allowed_radius,
                    "project_lat": project.site_latitude,
                    "project_lng": project.site_longitude,
                },
            )

    # Check photo quota (scoped to this project's own subscription tier)
    await assert_can_upload_photos(db, req.project_id, req.photo_count)

    # Create session
    session_id = new_id()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    session = UploadSession(
        id=session_id,
        developer_id=developer_id,
        project_id=req.project_id,
        capture_latitude=req.capture_latitude,
        capture_longitude=req.capture_longitude,
        accuracy_m=req.accuracy_m,
        photo_count=req.photo_count,
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()
    await db.commit()

    # Generate signing params for each photo
    signing_params = []
    for i in range(req.photo_count):
        params = get_signed_upload_params(
            folder=f"projects/{req.project_id}",
            public_id_prefix=f"{session_id}_{i}",
        )
        signing_params.append(params)

    return {
        "session_id": session_id,
        "signing_params": signing_params,
        "expires_at": expires_at,
    }


async def finalize_upload(
    db: AsyncSession, developer_id: str, req: FinalizeUploadRequest, idempotency_key: str
) -> Upload:
    """Create Upload + Photo records atomically after client uploads to Cloudinary."""
    # Check idempotency (deduplication via Idempotency-Key header)
    result = await db.execute(
        select(Upload).where(Upload.idempotency_key == idempotency_key)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    # Re-validate GPS (second layer)
    if req.accuracy_m > GPS_ACCURACY_THRESHOLD:
        raise GPSRejectedError(
            f"GPS accuracy too low: {req.accuracy_m}m",
            {"accuracy_m": req.accuracy_m},
        )

    result = await db.execute(
        select(Project).where(
            Project.id == req.project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    # ── SERVER-SIDE GPS VALIDATION (brief Section 5.1, defense in depth) ─────
    # The capture coordinate is the security boundary, re-validated here at
    # finalize. Outside the boundary is a hard reject with an audit-log record.
    distance = None
    within_boundary = True
    if project.site_latitude and project.site_longitude:
        distance = haversine_metres(
            req.capture_latitude, req.capture_longitude,
            project.site_latitude, project.site_longitude,
        )
        allowed_radius = project.gps_radius_metres + GPS_DISTANCE_BUFFER
        if distance > allowed_radius:
            within_boundary = False
            await log_action(
                db,
                actor_user_id=developer_id,
                actor_role="developer",
                action="upload.rejected.gps_outside_boundary",
                entity_type="upload_attempt",
                entity_id=req.project_id,
                developer_id=developer_id,
                after={
                    "distance_m": round(distance),
                    "radius_m": project.gps_radius_metres,
                    "capture_lat": req.capture_latitude,
                    "capture_lng": req.capture_longitude,
                },
            )
            raise GPSRejectedError(
                f"Upload coordinates are {distance:.0f}m from site (limit: {project.gps_radius_metres:.0f}m)",
                {
                    "code": "GPS_OUTSIDE_BOUNDARY",
                    "distance_m": round(distance),
                    "radius_m": project.gps_radius_metres,
                },
            )

    upload = Upload(
        id=new_id(),
        project_id=req.project_id,
        developer_id=developer_id,
        milestone_id=req.milestone_id,
        idempotency_key=idempotency_key,
        upload_session_id=req.session_id,
        caption=req.caption,
        title=getattr(req, "title", None),
        category=getattr(req, "category", None),
        progress_at_upload=getattr(req, "progress_at_upload", None),
        capture_latitude=req.capture_latitude,
        capture_longitude=req.capture_longitude,
        accuracy_m=req.accuracy_m,
        distance_from_site_m=distance,
        within_boundary=within_boundary,
        gps_validated=True,
        photo_count=len(req.photos),
        status="pending",
        flag_reason=None,
    )
    db.add(upload)
    await db.flush()

    # First construction update on the project moves it out of "planning" — the
    # project is now actively under construction, not just scheduled.
    if project.status == "planning":
        project.status = "active"

    for photo_input in req.photos:
        photo = Photo(
            id=new_id(),
            upload_id=upload.id,
            cloudinary_public_id=photo_input.cloudinary_public_id,
            cloudinary_url=photo_input.cloudinary_url,
            original_filename=photo_input.original_filename,
            capture_latitude=photo_input.capture_latitude or req.capture_latitude,
            capture_longitude=photo_input.capture_longitude or req.capture_longitude,
            accuracy_m=photo_input.accuracy_m or req.accuracy_m,
            width=photo_input.width,
            height=photo_input.height,
            file_size_bytes=photo_input.file_size_bytes,
            order_index=photo_input.order_index,
        )
        db.add(photo)

    await db.commit()
    await db.refresh(upload)
    return upload


async def list_uploads(
    db: AsyncSession, project_id: str, developer_id: str, page: int = 1, limit: int = 20
) -> tuple:
    from sqlalchemy import func

    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Project not found")

    offset = (page - 1) * limit
    result = await db.execute(
        select(Upload)
        .where(Upload.project_id == project_id, Upload.developer_id == developer_id)
        .order_by(Upload.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    uploads = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(Upload).where(
            Upload.project_id == project_id,
            Upload.developer_id == developer_id,
        )
    )
    total = count_result.scalar_one()
    return uploads, total


async def get_upload_with_photos(db: AsyncSession, upload_id: str, developer_id: str) -> tuple:
    result = await db.execute(
        select(Upload).where(
            Upload.id == upload_id,
            Upload.developer_id == developer_id,
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise NotFoundError("Upload not found")

    result = await db.execute(
        select(Photo).where(Photo.upload_id == upload_id).order_by(Photo.order_index)
    )
    photos = result.scalars().all()
    return upload, photos


def generate_whatsapp_draft(upload: Upload, project_name: str, photos: list) -> str:
    """Generate a WhatsApp-friendly text message for the upload."""
    lines = [
        f"*{project_name} - Site Update*",
        f"📸 {len(photos)} new photo(s) uploaded",
    ]
    if upload.caption:
        lines.append(f"\n_{upload.caption}_")
    if upload.created_at:
        lines.append(f"\n_Uploaded on {upload.created_at.strftime('%d %b %Y at %H:%M')} UTC_")
    return "\n".join(lines)
