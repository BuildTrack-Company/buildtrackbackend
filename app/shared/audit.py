from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import structlog

logger = structlog.get_logger(__name__)


async def log_action(
    db: AsyncSession,
    actor_user_id: str,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: str,
    developer_id: Optional[str] = None,
    before: Optional[Any] = None,
    after: Optional[Any] = None,
    metadata: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Log an audit action to the audit_log table."""
    try:
        from app.shared.ids import new_id
        import json

        await db.execute(
            text("""
                INSERT INTO audit_log (
                    id, actor_user_id, actor_role, action, entity_type, entity_id,
                    developer_id, before_state, after_state, metadata,
                    ip_address, user_agent, request_id, created_at
                ) VALUES (
                    :id, :actor_user_id, :actor_role, :action, :entity_type, :entity_id,
                    :developer_id, :before_state, :after_state, :metadata,
                    :ip_address, :user_agent, :request_id, :created_at
                )
            """),
            {
                "id": new_id(),
                "actor_user_id": actor_user_id,
                "actor_role": actor_role,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "developer_id": developer_id,
                "before_state": json.dumps(before) if before else None,
                "after_state": json.dumps(after) if after else None,
                "metadata": json.dumps(metadata) if metadata else None,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "request_id": request_id,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db.commit()
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e), action=action, entity_type=entity_type)
