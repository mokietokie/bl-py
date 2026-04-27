from __future__ import annotations
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import FileResponse

from bl_tracker.services import excel as excel_svc

router = APIRouter()


@router.post("/import/excel")
async def import_excel(req: Request, file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as t:
        t.write(await file.read())
        tmp = Path(t.name)
    n = excel_svc.import_xlsx(req.app.state.db, tmp)
    return {"imported": n}


@router.get("/export/excel")
def export_excel(req: Request):
    out = Path(tempfile.gettempdir()) / "shipments_export.xlsx"
    excel_svc.export_xlsx(req.app.state.db, out)
    return FileResponse(
        out,
        filename="shipments.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
