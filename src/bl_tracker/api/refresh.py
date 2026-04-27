from __future__ import annotations
import asyncio
import json
from typing import List, Literal
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from bl_tracker.services import refresh as svc

router = APIRouter()


@router.post("/shipments/{sid}/refresh-bl")
async def refresh_bl(sid: int, req: Request):
    return await svc.refresh_bl(req.app.state.db, sid)


@router.post("/shipments/{sid}/refresh-loc")
async def refresh_loc(sid: int, req: Request):
    return await svc.refresh_loc(req.app.state.db, sid)


class BulkIn(BaseModel):
    ids: List[int]
    targets: List[Literal["bl", "loc"]]


@router.post("/shipments/refresh-bulk")
async def refresh_bulk(payload: BulkIn, req: Request):
    db = req.app.state.db
    queue: asyncio.Queue = asyncio.Queue()

    def emit(p):
        queue.put_nowait(p)

    async def runner():
        await svc.refresh_bulk(db, payload.ids, payload.targets,
                               concurrency=3, on_progress=emit)
        await queue.put(None)

    async def stream():
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield {"event": "progress",
                       "data": json.dumps(item, ensure_ascii=False)}
        finally:
            await task

    return EventSourceResponse(stream())
