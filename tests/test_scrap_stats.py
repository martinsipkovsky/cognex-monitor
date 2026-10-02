"""Scrap statistics over a date range (Data log > Scrap statistics)."""
import datetime as dt
import io

from openpyxl import load_workbook

from app.database import SessionLocal
from app.models import Device, Reading

from test_api import login

UTC = dt.timezone.utc


def _seed():
    db = SessionLocal()
    try:
        cam = Device(name="Cam1", host="sim", port=0, protocol="simulator")
        db.add(cam)
        db.flush()

        def r(day, hour, job, p, f):
            db.add(Reading(device_id=cam.id, job_name=job, total_pass=p, total_fail=f,
                           created_at=dt.datetime(2026, 9, day, hour, tzinfo=UTC)))

        r(28, 22, "A", 100, 10)  # before the range: baseline only
        r(29, 8, "A", 190, 20)   # +90/+10 on the 29th
        r(29, 9, "B", 5, 5)      # job change: new baseline, not counted
        r(30, 8, "B", 45, 5)     # +40/+0 on the 30th
        r(30, 9, "B", 45, 8)     # +0/+3
        r(2, 8, "B", 999, 999)   # after the range
        db.commit()
    finally:
        db.close()


def test_scrap_range_per_camera_job_day(client):
    login(client)
    _seed()
    s = client.get("/api/data/scrap", params={"from": "2026-09-29", "to": "2026-09-30", "tz": "UTC"}).json()
    assert s["overall"] == {"pass": 130, "fail": 13, "total": 143, "scrap_rate": round(13 / 143, 4)}
    assert [(c["camera"], c["total"]) for c in s["per_camera"]] == [("Cam1", 143)]
    assert [(j["job"], j["pass"], j["fail"]) for j in s["per_job"]] == [("A", 90, 10), ("B", 40, 3)]
    assert [(d["day"], d["pass"], d["fail"]) for d in s["per_day"]] == [
        ("2026-09-29", 90, 10), ("2026-09-30", 40, 3)]


def test_scrap_days_follow_time_zone(client):
    login(client)
    _seed()
    # The 30th in Tokyo (UTC+9) runs from 15:00 UTC on the 29th, so the job B
    # reading at 09:00 UTC on the 29th is the baseline and both readings on
    # the 30th (08:00 and 09:00 UTC) fall inside it.
    s = client.get("/api/data/scrap", params={"from": "2026-09-30", "to": "2026-09-30", "tz": "Asia/Tokyo"}).json()
    assert [(d["day"], d["total"]) for d in s["per_day"]] == [("2026-09-30", 43)]


def test_scrap_xlsx_matches_screen(client):
    login(client)
    _seed()
    params = {"from": "2026-09-29", "to": "2026-09-30", "tz": "UTC"}
    resp = client.get("/api/data/scrap.xlsx", params=params)
    assert resp.status_code == 200
    assert "scrap_2026-09-29_2026-09-30.xlsx" in resp.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["Overall", "Per camera", "Per job", "Per day"]
    assert [c.value for c in wb["Overall"][2]] == ["2026-09-29 to 2026-09-30", 130, 13, 143, round(13 / 143, 4)]
    assert [c.value for c in wb["Per job"][3]][:5] == ["Cam1", "B", 40, 3, 43]
    assert wb["Per day"]["A2"].value.date() == dt.date(2026, 9, 29)


def test_scrap_range_validation_and_permission(client):
    login(client)
    assert client.get("/api/data/scrap", params={"from": "2026-09-30", "to": "2026-09-29"}).status_code == 400
    client.post("/api/users", json={"username": "viewer", "password": "pw123456", "permissions": ["view_dashboard"]})
    client.get("/logout")
    login(client, "viewer", "pw123456")
    assert client.get("/api/data/scrap", params={"from": "2026-09-29", "to": "2026-09-30"}).status_code == 403
