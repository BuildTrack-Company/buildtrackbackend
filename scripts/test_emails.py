import asyncio
import json
import httpx
from datetime import datetime

BASE_URL = "http://localhost:8000/v1"

async def test_emails():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. Register Developer
        print("Registering Developer...")
        res = await client.post("/admin/developers", json={
            "email": "nicanoraapolin@gmail.com",
            "password": "SecurePassword123!",
            "full_name": "Nicanor Apolin",
            "company_name": "Nicanor Construction",
            "subscription_tier": "trial"
        }, headers={"Authorization": "Bearer test-admin-token"})
        print("Register Dev Response:", res.status_code, res.text)
        
        # 2. Reset Password
        print("Reset Password...")
        res = await client.post("/auth/forgot-password", json={
            "email": "nicanoraapolin@gmail.com",
            "role": "developer"
        })
        print("Reset Password Response:", res.status_code, res.text)

        # 3. Add a Buyer
        # Need developer token. Let's just create a test script that directly calls service functions instead to avoid token dances.
        pass
