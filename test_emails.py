import requests
import json
import time

BASE_URL = "http://localhost:8000/v1"

def run_tests():
    print("1. Registering Developer (Should send OTP email)...")
    dev_req = {
        "email": "nicanoraapolin+3@gmail.com",
        "password": "Password123!",
        "full_name": "Nicanora Apolin",
        "company_name": "Apolin Builders",
        "phone": "+254700000001"
    }
    r = requests.post(f"{BASE_URL}/auth/register/developer", json=dev_req)
    print("Status:", r.status_code, r.text)
    
    if r.status_code in [200, 201]:
        token = r.json().get("data", {}).get("access_token")
    else:
        # if already exists, try logging in
        r2 = requests.post(f"{BASE_URL}/auth/login/developer", json={"email": dev_req["email"], "password": dev_req["password"]})
        if r2.status_code == 200:
            token = r2.json().get("data", {}).get("access_token")
        else:
            print("Failed to login as developer:", r2.text)
            return

    print("\n2. Triggering Password Reset for Developer (Should send Reset email)...")
    r = requests.post(f"{BASE_URL}/auth/password/reset/request", json={"email": "nicanoraapolin+3@gmail.com"})
    print("Status:", r.status_code, r.text)

    headers = {"Authorization": f"Bearer {token}"}

    print("\n3. Creating a Project...")
    proj_req = {
        "name": "The Grand Estate",
        "description": "Luxury villas",
        "county": "Nairobi",
        "constituency": "Westlands",
        "location_name": "Westlands Estate Area",
        "site_latitude": -1.25,
        "site_longitude": 36.8,
        "gps_radius_metres": 500,
        "total_units": 10,
        "is_public": True
    }
    r = requests.post(f"{BASE_URL}/projects", json=proj_req, headers=headers)
    print("Status:", r.status_code)
    if r.status_code not in [200, 201]:
        print(r.text)
        return
    project_id = r.json().get("data", {}).get("id")

    print("\n4. Inviting Buyer (Should send Buyer Invitation email)...")
    buyer_req = {
        "email": "donaldgenegunther@gmail.com",
        "full_name": "Donald Gene Gunther",
        "unit_number": "Villa 1"
    }
    r = requests.post(f"{BASE_URL}/projects/{project_id}/buyers/invite", json=buyer_req, headers=headers)
    print("Status:", r.status_code, r.text)

    print("\nCheck the inboxes of both emails to confirm they arrived!")

if __name__ == "__main__":
    run_tests()
