"""
Create or update admin user.
Run: .venv/Scripts/python scripts/create_admin.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.core.database import async_session_factory
from app.core.security import hash_password
from app.shared.ids import new_id
from app.modules.auth.models import User
from datetime import datetime, timezone


async def create_admin(email: str, password: str, full_name: str = "Admin"):
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.hashed_password = hash_password(password)
            user.role = "admin"
            user.is_active = True
            print(f"Updated admin: {email}")
        else:
            user = User(
                id=new_id(),
                email=email,
                hashed_password=hash_password(password),
                role="admin",
                full_name=full_name,
                is_active=True,
                email_verified=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(user)
            print(f"Created admin: {email}")
        await db.commit()


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@buildtrack.co.ke"
    password = sys.argv[2] if len(sys.argv) > 2 else "Admin@2026!"
    full_name = sys.argv[3] if len(sys.argv) > 3 else "BuildTrack Admin"
    asyncio.run(create_admin(email, password, full_name))
