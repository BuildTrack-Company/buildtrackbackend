"""One-shot fix: create and seed subscription_tier_limits in isolation."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()

raw_url = os.environ["DATABASE_URL"]
# Strip sslmode from URL — asyncpg requires connect_args instead
url = raw_url.replace("?sslmode=require", "").replace("&sslmode=require", "")

engine = create_async_engine(url, connect_args={"ssl": "require"}, echo=False)

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS subscription_tier_limits (
    tier            VARCHAR(20) PRIMARY KEY,
    max_projects    INTEGER NOT NULL,
    max_buyers_per_project INTEGER NOT NULL,
    max_photos_per_upload  INTEGER NOT NULL,
    photo_storage_gb       NUMERIC(10,2) NOT NULL,
    api_rate_limit_per_min INTEGER NOT NULL DEFAULT 60
)
"""

INSERT_SQL = """
INSERT INTO subscription_tier_limits
    (tier, max_projects, max_buyers_per_project, max_photos_per_upload, photo_storage_gb, api_rate_limit_per_min)
VALUES
    ('trial',        1,   50,  5,    1.00,  30),
    ('starter',      5,  100, 10,   10.00,  60),
    ('growth',      20,  500, 20,   50.00, 120),
    ('scale',      100, 2000, 50,  200.00, 300),
    ('enterprise', 999, 9999, 99, 1000.00, 600)
ON CONFLICT (tier) DO UPDATE SET
    max_projects = EXCLUDED.max_projects,
    max_buyers_per_project = EXCLUDED.max_buyers_per_project,
    max_photos_per_upload = EXCLUDED.max_photos_per_upload,
    photo_storage_gb = EXCLUDED.photo_storage_gb,
    api_rate_limit_per_min = EXCLUDED.api_rate_limit_per_min
"""

VERIFY_SQL = "SELECT tier, max_projects, max_photos_per_upload FROM subscription_tier_limits ORDER BY tier"


async def main():
    # Step 1: create + seed in its own committed transaction
    async with engine.begin() as conn:
        await conn.execute(text(CREATE_SQL))
        await conn.execute(text(INSERT_SQL))
    print("subscription_tier_limits created and seeded")

    # Step 2: verify in a fresh connection
    async with engine.begin() as conn:
        result = await conn.execute(text(VERIFY_SQL))
        rows = result.fetchall()
        print(f"Verified {len(rows)} tiers:")
        for row in rows:
            print(f"  {row[0]:12s}  max_projects={row[1]:4d}  max_photos={row[2]}")

    await engine.dispose()


asyncio.run(main())
