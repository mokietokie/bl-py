from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI

from bl_tracker.config import db_path
from .shipments import router as shipments_router


def build_app(db: Path | None = None) -> FastAPI:
    app = FastAPI(title="BL Tracker")
    app.state.db = db or db_path()
    app.include_router(shipments_router)
    return app


app = build_app()
