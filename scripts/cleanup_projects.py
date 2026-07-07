"""
Soft-delete all projects except the 4 pilot projects.
Run from the backend directory: python scripts/cleanup_projects.py
"""
import asyncio
from datetime import datetime, timezone
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

KEEP = [
    "Express View Residency",
    "Luna Oak Residency",
    "Highpoint 336 Residences",
    "Highpoint 336 Residence",   # include both spellings
    "Sycamore Residences",
]


async def run():
    from app.core.database import engine
    from sqlalchemy.ext.asyncio import AsyncConnection
    from sqlalchemy import text

    async with engine.connect() as conn:
        # List all active projects
        result = await conn.execute(text(
            "SELECT id, name FROM projects WHERE deleted_at IS NULL ORDER BY name"
        ))
        all_projects = result.fetchall()

        keep = [(row.id, row.name) for row in all_projects if row.name.strip() in KEEP]
        remove = [(row.id, row.name) for row in all_projects if row.name.strip() not in KEEP]

        print(f"\nKeeping {len(keep)} projects:")
        for pid, name in keep:
            print(f"  ✓ {name}")

        print(f"\nSoft-deleting {len(remove)} projects:")
        for pid, name in remove:
            print(f"  ✗ {name}")

        if not remove:
            print("\nNothing to delete.")
            return

        confirm = input(f"\nProceed with soft-deleting {len(remove)} projects? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

        ids_to_remove = [pid for pid, _ in remove]
        now = datetime.now(timezone.utc)
        await conn.execute(
            text("UPDATE projects SET deleted_at = :ts WHERE id = ANY(:ids)"),
            {"ts": now, "ids": ids_to_remove}
        )
        await conn.commit()
        print(f"\nDone. {len(remove)} projects soft-deleted.")


if __name__ == "__main__":
    asyncio.run(run())
