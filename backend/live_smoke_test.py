"""Live smoke test against running backend."""
import time

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


def wait_for_run(client, headers, run_id, acceptable, timeout=90.0, poll=0.5):
    """Poll workflow run until status reaches one of acceptable values."""
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        resp = client.get(f"/api/workflows/runs/{run_id}", headers=headers)
        resp.raise_for_status()
        run = resp.json()
        last_status = run.get("status")
        if last_status in acceptable:
            return run
        if last_status in ("failed", "cancelled"):
            raise RuntimeError(
                f"run #{run_id} ended as {last_status}: {run.get('error_message') or 'no detail'}"
            )
        time.sleep(poll)
    raise TimeoutError(f"run #{run_id} stuck at '{last_status}' (wanted {acceptable})")


with httpx.Client(base_url=BASE, timeout=60) as c:
    check("Health", lambda: c.get("/api/system/health").raise_for_status())
    login = c.post("/api/auth/login", json={"email": "priya@infosys.com", "password": "demo123"}).json()
    h = {"Authorization": f"Bearer {login['access_token']}"}
    check("Login", lambda: (_ for _ in ()).throw(Exception("no token")) if not login.get("access_token") else None)

    defs = c.get("/api/workflows/definitions", headers=h).json()
    check("Workflow Definitions", lambda: (_ for _ in ()).throw(Exception(f"only {len(defs)}")) if len(defs) < 3 else None)

    sim = c.post("/api/dev-collab/simulate-demo-conflict", headers=h, timeout=90.0)
    sim.raise_for_status()
    conflicts = c.get("/api/dev-collab/conflicts", headers=h).json()
    if not conflicts:
        raise RuntimeError("simulate-demo-conflict did not create a conflict")
    cid = conflicts[0]["id"]
    start_resp = c.post(
        "/api/workflows/start",
        headers=h,
        json={"template_key": "dev-conflict-resolution", "context": {"conflict_id": cid}},
        timeout=90.0,
    )
    start_resp.raise_for_status()
    started = start_resp.json()
    run_id = started["id"]
    w = wait_for_run(c, h, run_id, {"waiting_hitl"})
    check(
        "Workflow HITL Pause",
        lambda: (_ for _ in ()).throw(Exception(w["status"])) if w["status"] != "waiting_hitl" else None,
    )

    r = c.post(f"/api/workflows/runs/{run_id}/resume", headers=h)
    print("resume status", r.status_code, r.text[:500])
    r.raise_for_status()
    completed = wait_for_run(c, h, run_id, {"completed"})
    check(
        "Workflow Resume",
        lambda: (_ for _ in ()).throw(Exception(completed["status"]))
        if completed["status"] != "completed"
        else None,
    )

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
