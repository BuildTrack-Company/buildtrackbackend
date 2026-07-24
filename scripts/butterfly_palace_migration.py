"""
One-off migration for the Butterfly Palace pitch-demo -> real-pilot cutover.

1. Backs up the demo account's full row data to JSON (safety net before delete).
2. Moves the 4 real GPS-verified photos Alex uploaded (upload 019f8db2-d018)
   from the demo project/developer onto Summer's real account.
3. Updates Summer's real developer/project rows with the confirmed real
   developer + project details (company, overview, location, GPS, tagline,
   description, visibility publish). Milestone dates are left untouched
   (already unset) per explicit instruction from Alex.
4. Permanently deletes the demo Butterfly Palace project, developer, users,
   milestones, uploads/photos, workflow template/stages, buyer, and related
   rows (upload_sessions, visibility_page_views, notifications, role
   assignments, auth token denylist entries).

Run: backend/.venv/bin/python scripts/butterfly_palace_migration.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import async_session_factory

DEMO_PROJECT_ID = "019f8b94-c21c-7d82-9efc-0c6661ec1d12"
DEMO_DEV_ID = "019f8b94-2965-783b-ad4b-79397bbc40e8"
DEMO_USER_ID = "019f8b94-2808-7d5c-a6ab-e81fcf2606df"
DEMO_TEMPLATE_ID = "019f8b94-73ee-77ab-b63f-f2f8dcf673b2"
DEMO_BUYER_ID = "019f8bb2-a482-77f5-ad64-36b95fb167ad"
DEMO_BUYER_USER_ID = "019f8bb2-a366-7491-9eed-6d238057ff71"

REAL_PROJECT_ID = "019f8dcc-c348-7875-8f75-2e28b6bd839b"
REAL_DEV_ID = "019f8dc7-fd56-7008-903c-82d6a13d6c98"

MOVE_UPLOAD_ID = "019f8db2-d018-7627-923b-23adbde41bfd"  # 4 real photos, currently on demo acct

BACKUP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "seed_data", "butterfly_palace_demo_backup.json",
)

REAL_COMPANY_OVERVIEW = (
    "Kiu Development Company Limited is a Nairobi-based developer with 6 years in the "
    "market, delivering premium residential apartments. Before Butterfly Palace, the "
    "company completed Sunset Park in Mwanzi, near Westgate Mall. The company positions "
    "its developments at the upper end of the apartment market, with a focus on "
    "family-oriented homes in well-established, upscale neighborhoods."
)

REAL_DESCRIPTION = (
    "Butterfly Palace is a high-end residential development located along Donyo Sabuk "
    "Avenue in Westlands, in a well-established, palatial neighborhood with easy access "
    "from the road. The plot sits on a descending landscape from the road, providing a "
    "more stable foundation base for construction. The development comprises 75 units "
    "across 15 floors, with two units per floor, offered in three configurations: "
    "two-bedroom units (168 sqm), three-bedroom units (235 sqm), and four-bedroom units "
    "(377 sqm). The ground floor houses shared amenities, while Basement Levels 1 to 3 "
    "are dedicated to parking. Construction updates for this project are captured "
    "on-site, GPS-verified at the point of upload, and reviewed before publication, "
    "giving buyers an independently verifiable record of progress from foundation "
    "through handover."
)

REAL_TAGLINE = "A palatial family home in the heart of Westlands."


async def backup(db):
    async def rows(sql, params):
        r = (await db.execute(text(sql), params)).mappings().all()
        return [dict(x) for x in r]

    data = {
        "project": await rows("select * from projects where id=:p", {"p": DEMO_PROJECT_ID}),
        "developer": await rows("select * from developers where id=:d", {"d": DEMO_DEV_ID}),
        "user": await rows("select * from users where id=:u", {"u": DEMO_USER_ID}),
        "milestones": await rows("select * from milestones where project_id=:p", {"p": DEMO_PROJECT_ID}),
        "uploads": await rows("select * from uploads where project_id=:p", {"p": DEMO_PROJECT_ID}),
        "photos": await rows(
            "select * from photos where upload_id in (select id from uploads where project_id=:p)",
            {"p": DEMO_PROJECT_ID},
        ),
        "buyers": await rows("select * from buyers where project_id=:p", {"p": DEMO_PROJECT_ID}),
        "buyer_user": await rows("select * from users where id=:u", {"u": DEMO_BUYER_USER_ID}),
        "workflow_template": await rows("select * from workflow_templates where id=:w", {"w": DEMO_TEMPLATE_ID}),
        "workflow_stages": await rows("select * from workflow_stages where workflow_template_id=:w", {"w": DEMO_TEMPLATE_ID}),
        "upload_sessions": await rows("select * from upload_sessions where project_id=:p", {"p": DEMO_PROJECT_ID}),
        "project_units": await rows("select * from project_units where project_id=:p", {"p": DEMO_PROJECT_ID}),
    }

    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
    with open(BACKUP_PATH, "w") as f:
        json.dump(data, f, indent=2, default=default)
    print(f"Backed up demo account data -> {BACKUP_PATH}")


async def move_photos(db):
    await db.execute(
        text("update uploads set project_id=:rp, developer_id=:rd, updated_at=:now where id=:u"),
        {"rp": REAL_PROJECT_ID, "rd": REAL_DEV_ID, "now": datetime.now(timezone.utc), "u": MOVE_UPLOAD_ID},
    )
    print(f"Moved upload {MOVE_UPLOAD_ID} (4 photos) -> real project/developer")


async def update_real_account(db):
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "update developers set company_name=:cn, company_overview=:co, updated_at=:now where id=:d"
        ),
        {"cn": "Kiu Development Company Limited", "co": REAL_COMPANY_OVERVIEW, "now": now, "d": REAL_DEV_ID},
    )
    await db.execute(
        text(
            """update projects set
                location_name=:loc, site_latitude=:lat, site_longitude=:lng,
                description=:desc, visibility_description=:vdesc, visibility_tagline=:tag,
                visibility_page_published=true, is_public=true, updated_at=:now
               where id=:p"""
        ),
        {
            "loc": "Opposite 7 Heights Apartments, Donyo Sabuk Ave, Westlands, Nairobi",
            "lat": -1.251243,
            "lng": 36.797926,
            "desc": REAL_DESCRIPTION,
            "vdesc": REAL_DESCRIPTION,
            "tag": REAL_TAGLINE,
            "now": now,
            "p": REAL_PROJECT_ID,
        },
    )
    print("Updated real developer + project with confirmed details; visibility page published")


async def delete_demo_account(db):
    ms_ids = [r[0] for r in (await db.execute(
        text("select id from milestones where project_id=:p"), {"p": DEMO_PROJECT_ID}
    )).all()]
    up_ids = [r[0] for r in (await db.execute(
        text("select id from uploads where project_id=:p and id != :keep"),
        {"p": DEMO_PROJECT_ID, "keep": MOVE_UPLOAD_ID},
    )).all()]

    if ms_ids:
        await db.execute(text("delete from milestone_approvals where milestone_id = ANY(:ids)"), {"ids": ms_ids})
    if up_ids:
        await db.execute(text("delete from photos where upload_id = ANY(:ids)"), {"ids": up_ids})
        await db.execute(text("delete from uploads where id = ANY(:ids)"), {"ids": up_ids})

    await db.execute(text("delete from milestone_approvals where buyer_user_id=:u"), {"u": DEMO_BUYER_USER_ID})
    await db.execute(text("delete from notifications where user_id=:u"), {"u": DEMO_BUYER_USER_ID})
    await db.execute(text("delete from buyers where id=:b"), {"b": DEMO_BUYER_ID})
    await db.execute(text("delete from users where id=:u"), {"u": DEMO_BUYER_USER_ID})

    await db.execute(text("delete from upload_sessions where project_id=:p"), {"p": DEMO_PROJECT_ID})
    await db.execute(text("delete from visibility_page_views where project_id=:p"), {"p": DEMO_PROJECT_ID})
    await db.execute(text("delete from project_units where project_id=:p"), {"p": DEMO_PROJECT_ID})
    await db.execute(text("delete from notification_log where developer_id=:d"), {"d": DEMO_DEV_ID})
    await db.execute(text("delete from notifications where user_id=:u"), {"u": DEMO_USER_ID})
    await db.execute(text("delete from user_role_assignments where user_id=:u"), {"u": DEMO_USER_ID})
    await db.execute(text("delete from auth_token_deny_list where user_id=:u"), {"u": DEMO_USER_ID})

    await db.execute(text("delete from milestones where project_id=:p"), {"p": DEMO_PROJECT_ID})
    await db.execute(text("update projects set current_stage_id=null, workflow_template_id=null where id=:p"), {"p": DEMO_PROJECT_ID})
    await db.execute(text("delete from projects where id=:p"), {"p": DEMO_PROJECT_ID})
    await db.execute(text("delete from workflow_stages where workflow_template_id=:w"), {"w": DEMO_TEMPLATE_ID})
    await db.execute(text("delete from workflow_templates where id=:w"), {"w": DEMO_TEMPLATE_ID})
    await db.execute(text("delete from developers where id=:d"), {"d": DEMO_DEV_ID})
    await db.execute(text("delete from users where id=:u"), {"u": DEMO_USER_ID})

    print("Permanently deleted demo Butterfly Palace account (project, developer, users, milestones, uploads/photos, workflow template)")


async def main():
    async with async_session_factory() as db:
        await backup(db)
        await move_photos(db)
        await update_real_account(db)
        await delete_demo_account(db)
        await db.commit()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
