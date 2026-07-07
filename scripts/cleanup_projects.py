"""
Soft-delete all projects except the 4 pilot projects.
Run from the backend directory: python scripts/cleanup_projects.py
"""
import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.core.config import settings
from app.modules.projects.models import Project

KEEP = {
    "Express View Residency",
    "Luna Oak Residency",
    "Highpoint 336 Residences",
    "Sycamore Residences",
}


async def run():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        result = await db.execute(select(Project).where(Project.deleted_at.is_(None)))
        all_projects = result.scalars().all()

        keep = [p for p in all_projects if p.name.strip() in KEEP]
        remove = [p for p in all_projects if p.name.strip() not in KEEP]

        print(f"\nKeeping {len(keep)} projects:")
        for p in keep:
            print(f"  ✓ {p.name} (id={p.id})")

        print(f"\nSoft-deleting {len(remove)} projects:")
        for p in remove:
            print(f"  ✗ {p.name} (id={p.id})")

        if not remove:
            print("\nNothing to delete.")
            return

        confirm = input(f"\nProceed with soft-deleting {len(remove)} projects? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

        now = datetime.now(timezone.utc)
        for p in remove:
            p.deleted_at = now

        await db.commit()
        print(f"\nDone. {len(remove)} projects soft-deleted.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
