from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.deps import require_admin
from app.modules.auth.models import User
from app.modules.notifications.models import NotificationLog
from app.modules.notifications.schemas import NotificationLogResponse
from app.shared.response import paginated

router = APIRouter(tags=["notifications"])


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
