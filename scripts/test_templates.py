import asyncio
import os
import sys

# Ensure backend path is recognized
sys.path.append(os.path.dirname(__file__))

from app.shared.email import send_email

async def main():
    print("Testing buyer_update_notification.html.j2")
    try:
        await send_email(
            to="buildtrack.ke@gmail.com",
            subject="Test Update Email",
            template_name="buyer_update_notification.html.j2",
            template_context={
                "first_name": "Lawrence",
                "developer_company_name": "Test Dev Co",
                "project_name": "Test Project",
                "update_title": "Concrete poured",
                "update_category": "Milestone Update",
                "update_date": "16 Jun 2026",
                "update_time": "14:00 PM",
                "progress_percentage": 45,
                "milestone_name": "Foundation",
                "milestone_number": 2,
                "update_description": "We successfully poured the concrete today.",
                "photo_count": 3,
                "gps_coordinates": "-1.2, 36.8",
                "project_page_url": "https://buildtrack.co.ke/project/123",
            }
        )
        print("Update Email OK")
    except Exception as e:
        print("Update Email failed:", e)

    print("Testing milestone_revision.html.j2")
    try:
        await send_email(
            to="buildtrack.ke@gmail.com",
            subject="Test Milestone Email",
            template_name="milestone_revision.html.j2",
            template_context={
                "first_name": "Lawrence",
                "developer_company_name": "Test Dev Co",
                "project_name": "Test Project",
                "milestone_name": "Foundation",
                "old_date": "10 Jun 2026",
                "new_date": "20 Jun 2026",
                "reason": "Rain delays",
                "project_page_url": "https://buildtrack.co.ke/project/123",
            }
        )
        print("Milestone Email OK")
    except Exception as e:
        print("Milestone Email failed:", e)

    print("Testing buyer_invitation.html.j2")
    try:
        await send_email(
            to="buildtrack.ke@gmail.com",
            subject="Test Invitation Email",
            template_name="buyer_invitation.html.j2",
            template_context={
                "first_name": "Lawrence",
                "developer_name": "Test Dev Co",
                "project_name": "Test Project",
                "project_url": "https://buildtrack.co.ke/project/123",
                "portal_link": "https://buildtrack.co.ke/register?token=123",
            }
        )
        print("Invitation Email OK")
    except Exception as e:
        print("Invitation Email failed:", e)

    print("Testing buyer_registration_confirmation.html.j2")
    try:
        await send_email(
            to="buildtrack.ke@gmail.com",
            subject="Test Registration Email",
            template_name="buyer_registration_confirmation.html.j2",
            template_context={
                "first_name": "Lawrence",
                "project_name": "Test Project",
                "portal_link": "https://buildtrack.co.ke/register?token=123",
            }
        )
        print("Registration Email OK")
    except Exception as e:
        print("Registration Email failed:", e)

if __name__ == "__main__":
    asyncio.run(main())
