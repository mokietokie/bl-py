from __future__ import annotations
import sqlite3
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bl_tracker.db import repo

router = APIRouter()


class ShipmentIn(BaseModel):
    bl_no: str
    imo_no: Optional[str] = None
    memo: Optional[str] = None


class ShipmentPatch(BaseModel):
    bl_no: Optional[str] = None
    imo_no: Optional[str] = None
    memo: Optional[str] = None


def _db(req: Request):
    return req.app.state.db


@router.get("/shipments")
def list_(req: Request) -> list[dict[str, Any]]:
    return repo.list_shipments(_db(req))


@router.post("/shipments", status_code=201)
def create(payload: ShipmentIn, req: Request):
    try:
        return repo.create_shipment(_db(req), bl_no=payload.bl_no,
                                    imo_no=payload.imo_no, memo=payload.memo)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "duplicate bl_no")


@router.put("/shipments/{sid}")
def update(sid: int, payload: ShipmentPatch, req: Request):
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    s = repo.update_shipment(_db(req), sid, **fields)
    if not s:
        raise HTTPException(404)
    return s


@router.delete("/shipments/{sid}", status_code=204)
def delete(sid: int, req: Request):
    repo.delete_shipment(_db(req), sid)
