"""End-to-end API tests against an in-memory sqlite database.

Exercises login, RBAC, camera CRUD, a simulated poll that feeds the counters,
job-change handling and the notification pipeline (via a dummy webhook).
"""
def login(client, user="Admin", pw="1234"):
    r = client.post("/login", data={"username": user, "password": pw}, follow_redirects=False)
    assert r.status_code == 303, r.text


def test_login_required(client):
    r = client.get("/api/devices")
    assert r.status_code == 401


def test_admin_login_and_create_user_with_permissions(client):
    login(client)
    r = client.post("/api/users", json={
        "username": "line1", "password": "pw", "is_admin": False,
        "permissions": ["view_dashboard", "view_data"],
    })
    assert r.status_code == 201, r.text
    # the limited user cannot manage devices
    c2 = client
    c2.get("/logout")
    login(c2, "line1", "pw")
    assert c2.post("/api/devices", json={
        "name": "x", "host": "h", "protocol": "simulator",
    }).status_code == 403
    # but can read the dashboard summary
    assert c2.get("/api/data/summary").status_code == 200


def test_simulator_poll_accumulates_and_survives_reset(client):
    login(client)
    r = client.post("/api/devices", json={
        "name": "Cam1", "host": "sim", "port": 0, "protocol": "simulator",
        "protocol_config": {"jobs": ["JOB_A"], "parts_per_poll": 10, "fail_ratio": 0.1,
                            "reset_every": 2, "job_change_every": 0},
        "poll_interval": 1,
    })
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    totals = []
    for _ in range(6):
        pr = client.post(f"/api/devices/{did}/poll")
        assert pr.status_code == 200, pr.text
        totals.append(pr.json()["total_pass"] + pr.json()["total_fail"])

    # Totals must be monotonically non-decreasing despite the camera's raw
    # counters resetting to a low value on every other poll. The raw counter
    # never exceeds ~2 batches (20), so a final total well above that proves
    # the accumulation survived the resets rather than tracking the raw value.
    assert totals == sorted(totals)
    assert totals[-1] >= 30

    counters = client.get(f"/api/devices/{did}/counters").json()
    assert counters[0]["total_count"] == totals[-1]


def test_job_change_starts_new_counter(client):
    login(client)
    r = client.post("/api/devices", json={
        "name": "Cam2", "host": "sim", "port": 0, "protocol": "simulator",
        "protocol_config": {"jobs": ["A", "B"], "parts_per_poll": 5,
                            "reset_every": 0, "job_change_every": 2},
    })
    did = r.json()["id"]
    for _ in range(5):
        client.post(f"/api/devices/{did}/poll")
    counters = client.get(f"/api/devices/{did}/counters").json()
    jobs = {c["job_name"] for c in counters}
    assert {"A", "B"}.issubset(jobs)
    # exactly one active counter at a time
    assert sum(1 for c in counters if c["is_active"]) == 1


def test_notification_rule_fires_to_webhook(client, monkeypatch):
    login(client)
    # capture webhook deliveries instead of hitting the network
    sent = []

    import httpx

    class _Resp:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        sent.append((url, kwargs.get("json")))
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client.post("/api/notifications/providers", json={
        "name": "test", "kind": "whatsapp",
        "config": {"transport": "webhook", "url": "http://example/send"},
    })
    # scrap_rate >= 0 will always fire once there is data
    client.post("/api/notifications/rules", json={
        "name": "any scrap", "condition": "scrap_rate", "threshold": 0.0, "cooldown": 0,
    })
    r = client.post("/api/devices", json={
        "name": "Cam3", "host": "sim", "port": 0, "protocol": "simulator",
        "protocol_config": {"jobs": ["J"], "parts_per_poll": 10, "fail_ratio": 0.5},
    })
    did = r.json()["id"]
    # scrap alerts only go out for cameras in production
    client.post(f"/api/devices/{did}/production/start")
    client.post(f"/api/devices/{did}/poll")

    logs = client.get("/api/notifications/logs").json()
    assert any(l["delivered"] for l in logs), logs
    assert sent, "webhook was not called"
