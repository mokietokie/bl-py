import tempfile
from pathlib import Path
import pytest
from bl_tracker.db import connection, repo


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        connection.init(p)
        yield p


def test_create_and_get(db):
    s = repo.create_shipment(db, bl_no="BL1", imo_no="9999999")
    assert s["bl_no"] == "BL1"
    got = repo.get_shipment(db, s["id"])
    assert got["bl_no"] == "BL1"
    assert got["imo_no"] == "9999999"


def test_unique_bl(db):
    repo.create_shipment(db, bl_no="BL1", imo_no=None)
    with pytest.raises(Exception):
        repo.create_shipment(db, bl_no="BL1", imo_no=None)


def test_list_and_update_and_delete(db):
    a = repo.create_shipment(db, bl_no="A", imo_no="1")
    repo.create_shipment(db, bl_no="B", imo_no="2")
    assert len(repo.list_shipments(db)) == 2
    repo.update_shipment(db, a["id"], memo="hi")
    assert repo.get_shipment(db, a["id"])["memo"] == "hi"
    repo.delete_shipment(db, a["id"])
    assert len(repo.list_shipments(db)) == 1


def test_upsert_eta_snapshot(db):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    repo.upsert_eta_snapshot(db, s["id"], "2026-04-26", "ETA-A", "2026-04-26T01:00:00Z")
    repo.upsert_eta_snapshot(db, s["id"], "2026-04-26", "ETA-B", "2026-04-26T02:00:00Z")
    snap = repo.get_eta_snapshot(db, s["id"], "2026-04-26")
    assert snap["eta"] == "ETA-B"


def test_get_eta_snapshot_missing(db):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    assert repo.get_eta_snapshot(db, s["id"], "2026-04-25") is None
