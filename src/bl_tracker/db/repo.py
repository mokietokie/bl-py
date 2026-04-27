from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connection import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r) -> dict[str, Any] | None:
    return dict(r) if r else None


def create_shipment(db: Path, *, bl_no: str, imo_no: str | None,
                    memo: str | None = None) -> dict[str, Any]:
    now = _now()
    with connect(db) as c:
        cur = c.execute(
            "INSERT INTO shipments(bl_no, imo_no, memo, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (bl_no, imo_no, memo, now, now),
        )
        new_id = cur.lastrowid
    return get_shipment(db, new_id)


def get_shipment(db: Path, ship_id: int) -> dict[str, Any] | None:
    with connect(db) as c:
        return _row(c.execute(
            "SELECT * FROM shipments WHERE id=?", (ship_id,)).fetchone())


def list_shipments(db: Path) -> list[dict[str, Any]]:
    with connect(db) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM shipments ORDER BY id ASC").fetchall()]


def update_shipment(db: Path, ship_id: int, **fields) -> dict[str, Any] | None:
    if not fields:
        return get_shipment(db, ship_id)
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect(db) as c:
        c.execute(f"UPDATE shipments SET {cols} WHERE id=?",
                  (*fields.values(), ship_id))
    return get_shipment(db, ship_id)


def delete_shipment(db: Path, ship_id: int) -> None:
    with connect(db) as c:
        c.execute("DELETE FROM shipments WHERE id=?", (ship_id,))


def upsert_shipment_by_bl(db: Path, *, bl_no: str, imo_no: str | None,
                          memo: str | None = None) -> dict[str, Any]:
    """Used by Excel import. Creates if absent, updates imo/memo if present."""
    existing = None
    with connect(db) as c:
        existing = _row(c.execute(
            "SELECT * FROM shipments WHERE bl_no=?", (bl_no,)).fetchone())
    if existing:
        return update_shipment(db, existing["id"], imo_no=imo_no, memo=memo)
    return create_shipment(db, bl_no=bl_no, imo_no=imo_no, memo=memo)


def upsert_eta_snapshot(db: Path, shipment_id: int, kst_date: str,
                        eta: str | None, fetched_at: str) -> None:
    with connect(db) as c:
        c.execute(
            "INSERT INTO eta_snapshots(shipment_id, kst_date, eta, fetched_at) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(shipment_id, kst_date) DO UPDATE SET "
            "eta=excluded.eta, fetched_at=excluded.fetched_at",
            (shipment_id, kst_date, eta, fetched_at),
        )


def get_eta_snapshot(db: Path, shipment_id: int, kst_date: str) -> dict | None:
    with connect(db) as c:
        return _row(c.execute(
            "SELECT * FROM eta_snapshots WHERE shipment_id=? AND kst_date=?",
            (shipment_id, kst_date)).fetchone())
