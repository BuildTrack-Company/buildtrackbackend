# Role-based end-to-end test results

_Generated 2026-05-31T22:20:22 against http://127.0.0.1:8000_

**37/37 checks passed**

| Role | Check | Result | Detail |
|---|---|---|---|
| admin | login | PASS |  |
| admin | stats | PASS | status=200 |
| admin | list developers >=3 | PASS |  |
| admin | list projects enriched | PASS |  |
| admin | list uploads | PASS |  |
| admin | flagged uploads | PASS |  |
| admin | audit log | PASS |  |
| admin | inquiries | PASS |  |
| admin | site-visits overview | PASS |  |
| admin | record verification | PASS |  |
| developer | login | PASS |  |
| developer | profile | PASS |  |
| developer | stats | PASS |  |
| developer | activity feed | PASS |  |
| developer | leads inbox | PASS |  |
| developer | site-visit inbox | PASS |  |
| developer | tier limits | PASS |  |
| developer | list own projects | PASS |  |
| developer | create document | PASS | status=201 |
| developer | list documents | PASS |  |
| developer | confirm site visit | PASS | status=200 |
| manager | login | PASS |  |
| manager | can view projects | PASS |  |
| manager | invite buyer forbidden | PASS | status=403 |
| buyer | login | PASS |  |
| buyer | view own project | PASS |  |
| buyer | pending approvals | PASS |  |
| buyer | view documents | PASS |  |
| buyer | request site visit | PASS | status=201 |
| buyer | create project forbidden | PASS |  |
| public | directory | PASS |  |
| public | directory area filter | PASS |  |
| public | visibility page | PASS |  |
| public | log view | PASS |  |
| public | site visit request | PASS | status=201 |
| public | unknown slug 404 | PASS |  |
| public | protected endpoint 401 | PASS |  |
