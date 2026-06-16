import asyncio
import os
import sys

# Set up path to import app modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.core.database import async_session_factory
from app.modules.auth.service import send_verification_otp, generate_password_reset_token, send_password_reset_email
from app.modules.developers.models import Developer
from app.modules.buyers.service import invite_buyer
from app.modules.projects.models import Project
from app.shared.email import send_email
from app.shared.security import get_password_hash
from sqlalchemy import select
from datetime import datetime, timezone
import uuid

async def run():
    async with async_session_factory() as db:
        # Create developer Nicanor Apolin if not exists
        dev_email = "nicanoraapolin@gmail.com"
        result = await db.execute(select(Developer).where(Developer.email == dev_email))
        dev = result.scalar_one_or_none()
        
        if not dev:
            dev = Developer(
                id=str(uuid.uuid4()),
                email=dev_email,
                hashed_password=get_password_hash("Secure123!"),
                full_name="Nicanor Apolin",
                company_name="Apolin Construction",
                subscription_tier="trial"
            )
            db.add(dev)
            await db.commit()
            print("Created developer.")
        else:
            print("Developer already exists.")

        # Trigger "Reset Password"
        print("Sending password reset...")
        token = generate_password_reset_token(dev_email)
        await send_password_reset_email(dev_email, token, "developer")
        print("Password reset email sent.")

        # Send invite buyer
        buyer_email = "donaldgenegunther@gmail.com"
        
        # We need a project
        result = await db.execute(select(Project).where(Project.developer_id == dev.id))
        project = result.scalars().first()
        if not project:
            project = Project(
                id=str(uuid.uuid4()),
                developer_id=dev.id,
                project_code="APOLIN123",
                name="Apolin Heights",
                location_name="Nairobi",
                site_latitude=-1.2921,
                site_longitude=36.8219,
                gps_radius_metres=100.0,
                total_units=10
            )
            db.add(project)
            await db.commit()
            
        print("Inviting buyer...")
        try:
            buyer = await invite_buyer(
                db=db,
                project_id=project.id,
                developer_id=dev.id,
                email=buyer_email,
                full_name="Donald Gunther",
                phone_number=None,
                unit_number="A1",
                amount_paid=0.0,
                total_price=100000.0,
                csv_import=False
            )
            print("Buyer invited successfully.")
        except Exception as e:
            print(f"Buyer invite failed (possibly already exists): {e}")
            # Try to just send a generic notification to him
            await send_email(
                to=buyer_email,
                subject=f"Construction Update: {project.name}",
                template_name="buyer_update_notification.html.j2",
                template_context={
                    "first_name": "Donald Gunther",
                    "developer_company_name": "Apolin Construction",
                    "project_name": project.name,
                    "update_title": "Foundation Completed",
                    "update_category": "Milestone",
                    "update_date": "16 Jun 2026",
                    "update_time": "14:00 PM",
                    "progress_percentage": 10,
                    "milestone_name": "Foundation",
                    "milestone_number": 1,
                    "update_description": "We are glad to announce that the foundation is done.",
                    "photo_count": 3,
                    "gps_coordinates": "-1.2921, 36.8219",
                    "project_page_url": f"https://buildtrack.co.ke/project/{project.project_code}",
                }
            )
            print("Sent update email instead.")

if __name__ == "__main__":
    asyncio.run(run())
