"""Live smoke test against running backend."""
import httpx

BASE = "http://127.0.0.1:8000"
passed = 0
failed = 0


def check(name, fn):
    global passed, failed
    try:
        fn()
        print(f"PASS: {name}")
        passed += 1
    except Exception as exc:
        print(f"FAIL: {name} - {exc}")
        failed += 1


with httpx.Client(base_url=BASE, timeout=60) as c:
    check("Health", lambda: c.get("/api/system/health").raise_for_status())
    login = c.post("/api/auth/login", json={"email": "priya@infosys.com", "password": "demo123"}).json()
    h = {"Authorization": f"Bearer {login['access_token']}"}
    check("Login", lambda: (_ for _ in ()).throw(Exception("no token")) if not login.get("access_token") else None)

    defs = c.get("/api/workflows/definitions", headers=h).json()
    check("Workflow Definitions", lambda: (_ for _ in ()).throw(Exception(f"only {len(defs)}")) if len(defs) < 3 else None)

    c.post("/api/dev-collab/simulate-demo-conflict", headers=h)
    cid = c.get("/api/dev-collab/conflicts", headers=h).json()[0]["id"]
    w = c.post(
        "/api/workflows/start",
        headers=h,
        json={"template_key": "dev-conflict-resolution", "context": {"conflict_id": cid}},
    ).json()
    check("Workflow HITL Pause", lambda: (_ for _ in ()).throw(Exception(w["status"])) if w["status"] != "waiting_hitl" else None)

    r = c.post(f"/api/workflows/runs/{w['id']}/resume", headers=h)
    print("resume status", r.status_code, r.text[:500])
    r.raise_for_status()
    body = r.json()
    check("Workflow Resume", lambda: (_ for _ in ()).throw(Exception(body["status"])) if body["status"] != "completed" else None)

    summary = c.get("/api/monitoring/summary", headers=h).json()
    check("Monitoring Summary", lambda: (_ for _ in ()).throw(Exception("no services")) if not summary.get("services") else None)

    metrics = c.get("/api/system/agent-metrics", headers=h).json()
    check("Agent Metrics", lambda: (_ for _ in ()).throw(Exception("empty")) if metrics["total_decisions"] < 1 else None)

    inc = c.post("/api/incidents/simulate", headers=h).json()
    check("Simulate Incident", lambda: (_ for _ in ()).throw(Exception("no id")) if not inc.get("incident_id") else None)

    admin = c.post("/api/auth/login", json={"email": "admin@infosys.com", "password": "admin123"}).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    check("Admin Health", lambda: c.get("/api/admin/system-health", headers=ah).raise_for_status())

print(f"\n=== RESULT: {passed} passed, {failed} failed ===")
print("Frontend: http://localhost:5174  (or http://localhost:5173)")
print("Backend:  http://localhost:8000/docs")
