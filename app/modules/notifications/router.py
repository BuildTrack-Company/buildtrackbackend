from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.deps import require_admin, get_current_user
from app.modules.auth.models import User
from app.modules.notifications.models import NotificationLog, Notification
from app.modules.notifications.schemas import NotificationLogResponse
from app.shared.response import paginated, ok
from app.core.exceptions import NotFoundError

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def my_notifications(
    request: Request,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func

    rows = (await db.execute(
        select(Notification).where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc()).limit(limit)
    )).scalars().all()
    unread = (await db.execute(
        select(func.count()).select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
    )).scalar_one()
    data = [
        {
            "id": n.id, "type": n.type, "title": n.title, "body": n.body,
            "link": n.link, "read": n.read_at is not None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in rows
    ]
    return ok({"notifications": data, "unread_count": unread}, request=request)


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone

    n = (await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
    )).scalar_one_or_none()
    if not n:
        raise NotFoundError("Notification not found")
    if not n.read_at:
        n.read_at = datetime.now(timezone.utc)
        await db.commit()
    return ok({"id": notification_id, "read": True}, request=request)


@router.post("/notifications/read-all")
async def mark_all_read(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone
    from sqlalchemy import update

    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return ok({"message": "All notifications marked read"}, request=request)


@router.get("/admin/notification-log")
async def list_notification_log(
    request: Request,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func

    offset = (page - 1) * limit
    result = await db.execute(
        select(NotificationLog).order_by(NotificationLog.created_at.desc()).offset(offset).limit(limit)
    )
    logs = result.scalars().all()

    count_result = await db.execute(select(func.count()).select_from(NotificationLog))
    total = count_result.scalar_one()

    return paginated(
        [NotificationLogResponse.model_validate(l).model_dump() for l in logs],
        total, page, limit, request=request,
    )
