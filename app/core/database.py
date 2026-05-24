from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.core.config import settings
from typing import AsyncGenerator
import re


def _clean_db_url(url: str) -> tuple[str, dict]:
    """Remove sslmode from URL and return cleaned URL + connect_args."""
    connect_args = {}
    if "sslmode=require" in url:
        url = re.sub(r"[?&]sslmode=require", "", url)
        # Remove trailing ? if nothing else
        url = url.rstrip("?").rstrip("&")
        connect_args = {"ssl": "require"}
    return url, connect_args


_db_url, _connect_args = _clean_db_url(settings.DATABASE_URL)

engine = create_async_engine(
    _db_url,
    echo=settings.ENVIRONMENT == "development",
    pool_size=10,
    max_overflow=20,
    connect_args=_connect_args,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def set_rls_context(db: AsyncSession, tenant_id: str | None, role: str, user_id: str):
    """Set RLS session variables for multi-tenancy."""
    await db.execute(text(f"SET LOCAL app.current_tenant = '{tenant_id or ''}'"))
    await db.execute(text(f"SET LOCAL app.current_role = '{role}'"))
    await db.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))
