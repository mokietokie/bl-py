from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from bl_tracker.config import KST
from bl_tracker.crawler import track_trace as tt, vesselfinder as vf
from bl_tracker.db import repo


_fetch_eta: Callable[[str], Awaitable[dict]] = tt.fetch_eta
_fetch_location: Callable[[str], Awaitable[dict]] = vf.fetch_location


def _now_kst() -> datetime:
    return datetime.now(KST)


def _kst_today() -> str:
    return _now_kst().date().isoformat()


def _kst_today_minus(days: int) -> str:
    return (_now_kst().date() - timedelta(days=days)).isoformat()


async def refresh_bl(db: Path, shipment_id: int) -> dict[str, Any]:
    ship = repo.get_shipment(db, shipment_id)
    if not ship or not ship["bl_no"]:
        return {"status": "failed", "reason": "no_bl"}
    res = await _fetch_eta(ship["bl_no"])
    now_iso = _now_kst().isoformat()
    if res["status"] != "ok":
        return res
    new_eta = res["data"]["eta"]
    today = _kst_today()
    yesterday = _kst_today_minus(1)
    repo.upsert_eta_snapshot(db, shipment_id, today, new_eta, now_iso)
    prev = repo.get_eta_snapshot(db, shipment_id, yesterday)
    prev_eta = prev["eta"] if prev else None
    changed = 1 if (prev_eta is not None and prev_eta != new_eta) else 0
    repo.update_shipment(
        db, shipment_id,
        eta=new_eta,
        eta_prev_kst=prev_eta,
        eta_changed=changed,
        bl_refreshed_at=now_iso,
    )
    return {"status": "ok", "eta": new_eta, "changed": bool(changed)}


async def refresh_loc(db: Path, shipment_id: int) -> dict[str, Any]:
    ship = repo.get_shipment(db, shipment_id)
    if not ship or not ship["imo_no"]:
        return {"status": "failed", "reason": "no_imo"}
    res = await _fetch_location(ship["imo_no"])
    now_iso = _now_kst().isoformat()
    if res["status"] != "ok":
        return res
    d = res["data"]
    location = d.get("location_label") or d.get("area")
    repo.update_shipment(
        db, shipment_id,
        lat=d["lat"], lon=d["lon"],
        location=location,
        loc_refreshed_at=now_iso,
    )
    return {"status": "ok", "lat": d["lat"], "lon": d["lon"], "location": location}


async def refresh_bulk(db: Path, ids: list[int], targets: list[str],
                       concurrency: int = 3,
                       on_progress: Callable[[dict], None] | None = None
                       ) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    total = len(ids) * len(targets)
    done = 0
    results: list[dict] = []

    async def one(ship_id: int, target: str):
        nonlocal done
        async with sem:
            try:
                if target == "bl":
                    r = await refresh_bl(db, ship_id)
                else:
                    r = await refresh_loc(db, ship_id)
            except Exception as e:
                r = {"status": "failed", "reason": f"exception:{e}"}
            done += 1
            payload = {"shipment_id": ship_id, "target": target,
                       "result": r, "done": done, "total": total}
            results.append(payload)
            if on_progress:
                on_progress(payload)

    tasks = [one(i, t) for i in ids for t in targets]
    await asyncio.gather(*tasks)
    return results
