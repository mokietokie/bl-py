from __future__ import annotations
from pathlib import Path
from openpyxl import Workbook, load_workbook

from bl_tracker.db import repo

HEADERS = ["BL번호", "IMO번호", "ETA", "화물위치", "이전 ETA", "변경", "갱신시각(BL)", "갱신시각(위치)", "메모"]


def import_xlsx(db: Path, file: Path) -> int:
    wb = load_workbook(file, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0
    header = rows[0]
    bl_idx = 0
    imo_idx = 1
    count = 0
    for r in rows[1:]:
        if not r or r[bl_idx] in (None, ""):
            continue
        bl_no = str(r[bl_idx]).strip()
        imo_no = str(r[imo_idx]).strip() if len(r) > imo_idx and r[imo_idx] not in (None, "") else None
        memo = str(r[8]).strip() if len(r) > 8 and r[8] not in (None, "") else None
        repo.upsert_shipment_by_bl(db, bl_no=bl_no, imo_no=imo_no, memo=memo)
        count += 1
    return count


def export_xlsx(db: Path, file: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "shipments"
    ws.append(HEADERS)
    for s in repo.list_shipments(db):
        ws.append([
            s["bl_no"], s["imo_no"], s["eta"], s["location"],
            s["eta_prev_kst"], "Y" if s["eta_changed"] else "",
            s["bl_refreshed_at"], s["loc_refreshed_at"], s["memo"],
        ])
    wb.save(file)
    return file
