import tempfile
from pathlib import Path
from datetime import datetime
import pytest

from bl_tracker.db import connection, repo
from bl_tracker.services import refresh


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        connection.init(p)
        yield p


async def fake_eta_ok(bl):
    return {"status": "ok", "data": {"eta": "2026-05-03 14:00 KST", "port": "Busan"},
            "fetched_at": "2026-04-27T01:00:00Z", "bl_no": bl}


async def fake_eta_failed(bl):
    return {"status": "failed", "reason": "not_found",
            "fetched_at": "2026-04-27T01:00:00Z", "bl_no": bl}


async def fake_loc_ok(imo):
    return {"status": "ok", "data": {"lat": 35.1, "lon": 129.0,
            "area": "Off Busan", "vessel": "MV TEST"},
            "fetched_at": "2026-04-27T01:00:00Z", "imo": imo}


async def test_refresh_bl_marks_changed_when_yesterday_differs(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    yesterday = refresh._kst_today_minus(1)
    repo.upsert_eta_snapshot(db, s["id"], yesterday, "OLD-ETA", "2026-04-26T...Z")
    monkeypatch.setattr(refresh, "_fetch_eta", fake_eta_ok)
    out = await refresh.refresh_bl(db, s["id"])
    assert out["status"] == "ok"
    fresh = repo.get_shipment(db, s["id"])
    assert fresh["eta"] == "2026-05-03 14:00 KST"
    assert fresh["eta_prev_kst"] == "OLD-ETA"
    assert fresh["eta_changed"] == 1


async def test_refresh_bl_no_yesterday_means_not_changed(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    monkeypatch.setattr(refresh, "_fetch_eta", fake_eta_ok)
    await refresh.refresh_bl(db, s["id"])
    fresh = repo.get_shipment(db, s["id"])
    assert fresh["eta_changed"] == 0
    assert fresh["eta_prev_kst"] is None


async def test_refresh_bl_failed_keeps_previous(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    repo.update_shipment(db, s["id"], eta="KEEP")
    monkeypatch.setattr(refresh, "_fetch_eta", fake_eta_failed)
    out = await refresh.refresh_bl(db, s["id"])
    assert out["status"] == "failed"
    fresh = repo.get_shipment(db, s["id"])
    assert fresh["eta"] == "KEEP"


async def test_refresh_loc_writes_lat_lon_area(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no="9999999")
    monkeypatch.setattr(refresh, "_fetch_location", fake_loc_ok)
    await refresh.refresh_loc(db, s["id"])
    fresh = repo.get_shipment(db, s["id"])
    assert abs(fresh["lat"] - 35.1) < 1e-6
    assert fresh["location"] == "Off Busan"
