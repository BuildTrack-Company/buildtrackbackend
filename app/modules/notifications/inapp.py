"""Helpers for creating in-app notifications (the bell feed)."""
from datetime import datetime, timezone
from typing import Iterable, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.modules.notifications.models import Notification
from app.shared.ids import new_id

logger = structlog.get_logger(__name__)


async def create_notification(
    db: AsyncSession,
    user_id: Optional[str],
    title: str,
    body: Optional[str] = None,
    type: str = "info",
    link: Optional[str] = None,
    commit: bool = True,
) -> Optional[Notification]:
    if not user_id:
        return None
    n = Notification(
        id=new_id(), user_id=user_id, type=type, title=title, body=body,
        link=link, created_at=datetime.now(timezone.utc),
    )
    db.add(n)
    if commit:
        await db.commit()
    return n


async def create_for_users(
    db: AsyncSession,
    user_ids: Iterable[str],
    title: str,
    body: Optional[str] = None,
    type: str = "info",
    link: Optional[str] = None,
) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for uid in {u for u in user_ids if u}:
        db.add(Notification(id=new_id(), user_id=uid, type=type, title=title, body=body, link=link, created_at=now))
        count += 1
    if count:
        await db.commit()
    return count
