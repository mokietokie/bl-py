import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from bl_tracker.db import connection
from bl_tracker.api.app import build_app


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        connection.init(p)
        app = build_app(db=p)
        with TestClient(app) as c:
            yield c


def test_create_list_update_delete(client):
    r = client.post("/shipments", json={"bl_no": "BL1", "imo_no": "1"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.get("/shipments").json()[0]["bl_no"] == "BL1"
    r = client.put(f"/shipments/{sid}", json={"memo": "x"})
    assert r.json()["memo"] == "x"
    assert client.delete(f"/shipments/{sid}").status_code == 204
    assert client.get("/shipments").json() == []


def test_duplicate_bl_returns_409(client):
    client.post("/shipments", json={"bl_no": "BL1"})
    r = client.post("/shipments", json={"bl_no": "BL1"})
    assert r.status_code == 409


from openpyxl import Workbook


def test_excel_import_export_roundtrip(client, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["BL번호", "IMO번호", "ETA", "화물위치"])
    ws.append(["BL1", "111", "", ""])
    f = tmp_path / "in.xlsx"
    wb.save(f)
    with open(f, "rb") as fh:
        r = client.post("/import/excel", files={"file": ("in.xlsx", fh,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    assert r.json()["imported"] == 1
    r = client.get("/export/excel")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/")
    assert len(r.content) > 0
