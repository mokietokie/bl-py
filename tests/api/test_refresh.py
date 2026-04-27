import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from bl_tracker.db import connection, repo
from bl_tracker.api.app import build_app
from bl_tracker.services import refresh as refresh_svc


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        connection.init(p)

        async def fake_eta(bl):
            return {"status": "ok", "data": {"eta": f"ETA-{bl}", "port": "Busan"},
                    "fetched_at": "2026-04-27T01:00:00Z", "bl_no": bl}

        async def fake_loc(imo):
            return {"status": "ok",
                    "data": {"lat": 1.0, "lon": 2.0, "area": "X", "vessel": "v"},
                    "fetched_at": "2026-04-27T01:00:00Z", "imo": imo}

        monkeypatch.setattr(refresh_svc, "_fetch_eta", fake_eta)
        monkeypatch.setattr(refresh_svc, "_fetch_location", fake_loc)

        app = build_app(db=p)
        with TestClient(app) as c:
            c.db_path = p
            yield c


def test_single_bl_refresh(client):
    s = repo.create_shipment(client.db_path, bl_no="BL1", imo_no="1")
    r = client.post(f"/shipments/{s['id']}/refresh-bl")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_single_loc_refresh(client):
    s = repo.create_shipment(client.db_path, bl_no="BL1", imo_no="1")
    r = client.post(f"/shipments/{s['id']}/refresh-loc")
    assert r.status_code == 200


def test_bulk_sse_emits_progress(client):
    a = repo.create_shipment(client.db_path, bl_no="A", imo_no="1")
    b = repo.create_shipment(client.db_path, bl_no="B", imo_no="2")
    with client.stream("POST", "/shipments/refresh-bulk",
                       json={"ids": [a["id"], b["id"]],
                             "targets": ["bl", "loc"]}) as r:
        events = [line for line in r.iter_lines() if line.startswith("data:")]
    assert len(events) >= 4  # 2 ids x 2 targets
