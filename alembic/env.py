import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import Base

# Import all models so they register with Base
from app.modules.auth.models import User, AuthTokenDenyList, PasswordResetToken
from app.modules.developers.models import Developer
from app.modules.projects.models import Project
from app.modules.milestones.models import Milestone
from app.modules.uploads.models import Upload, Photo, UploadSession
from app.modules.buyers.models import Buyer
from app.modules.notifications.models import NotificationLog
from app.modules.admin.models import AuditLog, AdminIpAllowlist
from app.modules.webhooks.models import WebhookEvent

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Use direct URL for migrations (not pooler)
# Convert sslmode query param to connect_args for asyncpg
import re
_raw_url = settings.DATABASE_DIRECT_URL
if "sslmode=require" in _raw_url:
    _raw_url = re.sub(r"[?&]sslmode=require", "", _raw_url)
    database_url = _raw_url
    # For asyncpg, SSL is handled via connect_args
    _ssl_connect_args = {"ssl": "require"}
else:
    database_url = _raw_url
    _ssl_connect_args = {}


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_ssl_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
