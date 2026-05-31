"""
Role-based end-to-end smoke test against a RUNNING BuildTrack API.

Exercises the happy path (plus key permission boundaries) for every role:
  Admin, Developer owner, Site manager, Buyer, Prospective buyer (no auth).

Usage:
  # backend must be running on http://127.0.0.1:8000 and demo seed applied
  .venv/Scripts/python tests/integration/test_full_role_flows.py

Writes a pass/fail report to tests/integration/results.md and exits non-zero
if any check fails.
"""
import os
import sys
import json
import datetime
import httpx

BASE = os.environ.get("BT_API", "http://127.0.0.1:8000")
PASSWORDS = {
    "admin": ("admin@buildtrack.co.ke", "Admin@2026!", "/v1/auth/login/admin"),
    "developer": ("developer@acme.co.ke", "Developer@2026!", "/v1/auth/login/developer"),
    "manager": ("site.manager@acme.co.ke", "Manager@2026!", "/v1/auth/login/developer"),
    "buyer": ("buyer.diaspora@test.com", "Buyer@2026!", "/v1/auth/login/buyer"),
}

results = []  # (role, name, ok, detail)


def check(role, name, cond, detail=""):
    results.append((role, name, bool(cond), detail))
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {role}: {name} {('- ' + detail) if detail and not cond else ''}")


def login(client, role):
    email, pw, path = PASSWORDS[role]
    r = client.post(f"{BASE}{path}", json={"email": email, "password": pw})
    if r.status_code != 200:
        return None
    return r.json()["data"]["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    with httpx.Client(timeout=30.0) as c:
        # ---- ADMIN ----
        print("\n== ADMIN ==")
        t = login(c, "admin")
        check("admin", "login", t is not None)
        if t:
            h = auth(t)
            r = c.get(f"{BASE}/v1/admin/stats", headers=h)
            check("admin", "stats", r.status_code == 200 and r.json()["data"]["total_developers"] >= 3,
                  f"status={r.status_code}")
            r = c.get(f"{BASE}/v1/admin/developers?limit=50", headers=h)
            check("admin", "list developers >=3", r.status_code == 200 and len(r.json()["data"]) >= 3)
            r = c.get(f"{BASE}/v1/admin/projects?limit=50", headers=h)
            check("admin", "list projects enriched", r.status_code == 200 and r.json()["data"][0].get("developer_name") is not None)
            r = c.get(f"{BASE}/v1/admin/uploads?limit=20", headers=h)
            check("admin", "list uploads", r.status_code == 200 and r.json()["meta"]["pagination"]["total"] >= 40)
            r = c.get(f"{BASE}/v1/admin/uploads/flagged", headers=h)
            check("admin", "flagged uploads", r.status_code == 200)
            r = c.get(f"{BASE}/v1/admin/audit-log?limit=10", headers=h)
            check("admin", "audit log", r.status_code == 200 and len(r.json()["data"]) > 0)
            r = c.get(f"{BASE}/v1/admin/inquiries", headers=h)
            check("admin", "inquiries", r.status_code == 200)
            r = c.get(f"{BASE}/v1/admin/site-visits", headers=h)
            check("admin", "site-visits overview", r.status_code == 200)
            # record independent verification on first project
            pid = c.get(f"{BASE}/v1/admin/projects?limit=1", headers=h).json()["data"][0]["id"]
            r = c.post(f"{BASE}/v1/admin/projects/{pid}/independent-verification", headers=h,
                       json={"verifier_name": "QA", "outcome": "passed", "notes": "ok"})
            check("admin", "record verification", r.status_code == 200)

        # ---- DEVELOPER ----
        print("\n== DEVELOPER (owner) ==")
        t = login(c, "developer")
        check("developer", "login", t is not None)
        if t:
            h = auth(t)
            r = c.get(f"{BASE}/v1/developers/me", headers=h)
            check("developer", "profile", r.status_code == 200)
            dev_id = r.json()["data"]["id"] if r.status_code == 200 else None
            r = c.get(f"{BASE}/v1/developers/stats", headers=h)
            check("developer", "stats", r.status_code == 200)
            r = c.get(f"{BASE}/v1/developers/me/activity?limit=10", headers=h)
            check("developer", "activity feed", r.status_code == 200)
            r = c.get(f"{BASE}/v1/developers/me/inquiries", headers=h)
            check("developer", "leads inbox", r.status_code == 200)
            r = c.get(f"{BASE}/v1/developers/me/site-visits", headers=h)
            check("developer", "site-visit inbox", r.status_code == 200)
            r = c.get(f"{BASE}/v1/billing/tier-limits", headers=h)
            check("developer", "tier limits", r.status_code == 200)
            # own projects only
            r = c.get(f"{BASE}/v1/projects", headers=h)
            check("developer", "list own projects", r.status_code == 200)

        # ---- SITE MANAGER (permission boundary) ----
        print("\n== SITE MANAGER ==")
        t = login(c, "manager")
        check("manager", "login", t is not None)
        if t:
            h = auth(t)
            r = c.get(f"{BASE}/v1/projects", headers=h)
            check("manager", "can view projects", r.status_code == 200)
            # invite buyer should be forbidden (no buyers.create permission)
            r = c.post(f"{BASE}/v1/projects/{pid}/buyers/invite", headers=h,
                       json={"email": "x@y.com", "full_name": "X", "unit_number": "Z1"})
            check("manager", "invite buyer forbidden", r.status_code in (403, 404), f"status={r.status_code}")

        # ---- BUYER ----
        print("\n== BUYER ==")
        t = login(c, "buyer")
        check("buyer", "login", t is not None)
        if t:
            h = auth(t)
            r = c.get(f"{BASE}/v1/buyer/project", headers=h)
            check("buyer", "view own project", r.status_code == 200)
            r = c.get(f"{BASE}/v1/buyer/milestones/pending-approval", headers=h)
            check("buyer", "pending approvals", r.status_code == 200)
            r = c.post(f"{BASE}/v1/buyer/site-visits", headers=h,
                       json={"full_name": "Buyer Visit", "email": "buyer.diaspora@test.com",
                             "phone": "+254700000000", "requested_date": "2026-07-01", "party_size": 1})
            check("buyer", "request site visit", r.status_code == 201, f"status={r.status_code}")
            # cannot create a project
            r = c.post(f"{BASE}/v1/projects", headers=h, json={"name": "Hack", "total_units": 1})
            check("buyer", "create project forbidden", r.status_code in (403, 422))

        # ---- PROSPECTIVE BUYER (no auth) ----
        print("\n== PROSPECTIVE BUYER (public) ==")
        r = c.get(f"{BASE}/v1/public/directory")
        check("public", "directory", r.status_code == 200 and len(r.json()["data"]) >= 1)
        slug = None
        if r.status_code == 200 and r.json()["data"]:
            slug = r.json()["data"][0].get("slug")
        r = c.get(f"{BASE}/v1/public/directory?area=Kilimani")
        check("public", "directory area filter", r.status_code == 200)
        if slug:
            r = c.get(f"{BASE}/v1/public/projects/{slug}")
            check("public", "visibility page", r.status_code == 200)
            r = c.post(f"{BASE}/v1/public/projects/{slug}/view", json={"session_id": "sess-test"})
            check("public", "log view", r.status_code in (200, 202))
            r = c.post(f"{BASE}/v1/public/projects/{slug}/site-visits",
                       json={"full_name": "Prospect", "email": "p@x.com", "phone": "+254711000000",
                             "requested_date": "2026-07-10", "party_size": 1})
            check("public", "site visit request", r.status_code == 201, f"status={r.status_code}")
        # unpublished slug -> 404
        r = c.get(f"{BASE}/v1/public/projects/this-does-not-exist-xyz")
        check("public", "unknown slug 404", r.status_code == 404)
        # authenticated endpoint without token -> 401
        r = c.get(f"{BASE}/v1/admin/stats")
        check("public", "protected endpoint 401", r.status_code == 401)

    # ---- report ----
    passed = sum(1 for *_, ok, _ in [(0, 0, r[2], r[3]) for r in results] if ok)
    total = len(results)
    write_report(results, passed, total)
    print(f"\n==== {passed}/{total} checks passed ====")
    return 0 if passed == total else 1


def write_report(rows, passed, total):
    out = ["# Role-based end-to-end test results", "",
           f"_Generated {datetime.datetime.now().isoformat(timespec='seconds')} against {BASE}_", "",
           f"**{passed}/{total} checks passed**", "",
           "| Role | Check | Result | Detail |", "|---|---|---|---|"]
    for role, name, ok, detail in rows:
        out.append(f"| {role} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    path = os.path.join(os.path.dirname(__file__), "results.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"report written to {path}")


if __name__ == "__main__":
    sys.exit(main())
