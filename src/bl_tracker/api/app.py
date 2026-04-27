from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from bl_tracker.config import db_path
from .shipments import router as shipments_router
from .refresh import router as refresh_router
from .excel import router as excel_router


def build_app(db: Path | None = None) -> FastAPI:
    app = FastAPI(title="BL Tracker")
    app.state.db = db or db_path()
    app.include_router(shipments_router)
    app.include_router(refresh_router)
    app.include_router(excel_router)

    web_dir = Path(__file__).parent.parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(web_dir / "index.html")

    return app


app = build_app()
