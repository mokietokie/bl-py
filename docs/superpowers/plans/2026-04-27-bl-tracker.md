# BL Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local Windows `.exe` web app that replaces an Excel-based daily BL ETA + vessel location tracking workflow, with manual refresh buttons, KST date-based ETA change detection, and Playwright crawlers for `track-trace.com` and `vesselfinder.com`.

**Architecture:** FastAPI server bound to `127.0.0.1:7777`, SQLite local DB, vanilla HTML+HTMX frontend, two independently runnable Playwright crawler modules (CLI testable). PyInstaller bundles everything into a single `.exe`. 3-way concurrency for bulk refresh via asyncio Semaphore + SSE progress.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Playwright (Chromium), playwright-stealth, SQLite (stdlib `sqlite3`), openpyxl, HTMX, PyInstaller, pytest.

**Spec:** `docs/superpowers/specs/2026-04-27-bl-tracker-design.md`

**User checkpoint:** After Phase 2 (Tasks 3-4), the user will run the two crawlers from CLI with real BL / IMO numbers to validate before continuing. Stop and wait for green light.

---

## File Structure

```
bl-py/
├── pyproject.toml
├── .gitignore
├── src/bl_tracker/
│   ├── __init__.py
│   ├── __main__.py            # exe entry point
│   ├── config.py              # paths, ports, KST tz
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── _browser.py        # shared Playwright context factory + stealth
│   │   ├── track_trace.py     # fetch_eta + CLI
│   │   └── vesselfinder.py    # fetch_location + CLI
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql
│   │   ├── connection.py
│   │   └── repo.py            # shipments + eta_snapshots queries
│   ├── services/
│   │   ├── __init__.py
│   │   ├── refresh.py         # orchestrates crawler -> repo, KST compare
│   │   └── excel.py           # import/export xlsx
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py             # FastAPI app factory
│   │   ├── shipments.py       # CRUD routes
│   │   └── refresh.py         # single + bulk + SSE
│   └── web/
│       ├── index.html
│       └── app.js
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── track_trace_ok.html
│   │   ├── track_trace_notfound.html
│   │   ├── vesselfinder_ok.html
│   │   └── vesselfinder_notfound.html
│   ├── crawler/
│   │   ├── test_track_trace_parser.py
│   │   └── test_vesselfinder_parser.py
│   ├── db/
│   │   └── test_repo.py
│   ├── services/
│   │   ├── test_refresh.py
│   │   └── test_excel.py
│   └── api/
│       ├── test_shipments.py
│       └── test_refresh.py
└── packaging/
    └── bl_tracker.spec        # PyInstaller spec
```

Each crawler is split into a pure parser (testable against HTML fixtures) and a thin Playwright fetch wrapper. Refresh orchestration (KST compare, snapshot upsert) lives in `services/refresh.py`, not in the API or crawler.

---

## Phase 1 — Project Skeleton

### Task 1: pyproject + .gitignore + base layout

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/bl_tracker/__init__.py` (empty)
- Create: `src/bl_tracker/config.py`

- [ ] **Step 1: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
.mypy_cache/
build/
dist/
*.spec.bak
*.sqlite
*.sqlite-journal
.DS_Store
node_modules/
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "bl-tracker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "playwright>=1.42",
  "playwright-stealth>=1.0.6",
  "openpyxl>=3.1",
  "python-multipart>=0.0.9",
  "sse-starlette>=2.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "pyinstaller>=6.5",
]

[project.scripts]
bl-tracker = "bl_tracker.__main__:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Write `src/bl_tracker/config.py`**

```python
from __future__ import annotations
import os
import sys
from datetime import timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
HOST = "127.0.0.1"
PORT = 7777


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "bl-tracker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return app_data_dir() / "db.sqlite"
```

- [ ] **Step 4: Create venv + install**

Run:
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```
Expected: no errors; `playwright` binary available.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore src/bl_tracker/__init__.py src/bl_tracker/config.py
git commit -m "chore: project skeleton + config"
```

---

## Phase 2 — Crawlers (CLI testable)

### Task 2: Shared browser context factory

**Files:**
- Create: `src/bl_tracker/crawler/__init__.py` (empty)
- Create: `src/bl_tracker/crawler/_browser.py`

- [ ] **Step 1: Write `_browser.py`**

```python
from __future__ import annotations
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, BrowserContext
from playwright_stealth import stealth_async

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@asynccontextmanager
async def browser_context(headless: bool = True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx: BrowserContext = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        try:
            yield ctx
        finally:
            await ctx.close()
            await browser.close()


async def stealth_page(ctx: BrowserContext):
    page = await ctx.new_page()
    await stealth_async(page)
    return page
```

- [ ] **Step 2: Commit**

```bash
git add src/bl_tracker/crawler/__init__.py src/bl_tracker/crawler/_browser.py
git commit -m "feat(crawler): shared browser context factory with stealth"
```

---

### Task 3: track-trace.com crawler (parser + fetch + CLI)

**Files:**
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/fixtures/`
- Create: `tests/fixtures/track_trace_ok.html`
- Create: `tests/fixtures/track_trace_notfound.html`
- Create: `tests/crawler/__init__.py`, `tests/crawler/test_track_trace_parser.py`
- Create: `src/bl_tracker/crawler/track_trace.py`

- [ ] **Step 1: Write conftest + minimal fixtures**

`tests/conftest.py`:
```python
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")
    return _read
```

`tests/fixtures/track_trace_ok.html` (placeholder structure — will be replaced with real captured HTML during live spike; parser must be selector-driven so updating the fixture is enough):
```html
<!doctype html>
<html><body>
<table class="tracking-results">
  <tr><th>BL</th><td data-field="bl">SZPVAN2503001</td></tr>
  <tr><th>Final Port</th><td data-field="port">Busan, KR</td></tr>
  <tr><th>ETA</th><td data-field="eta">2026-05-03 14:00 KST</td></tr>
</table>
</body></html>
```

`tests/fixtures/track_trace_notfound.html`:
```html
<!doctype html>
<html><body>
<div class="error">No tracking information found</div>
</body></html>
```

- [ ] **Step 2: Write failing parser tests**

`tests/crawler/__init__.py`: empty.
`tests/crawler/test_track_trace_parser.py`:
```python
from bl_tracker.crawler.track_trace import parse_eta


def test_parses_eta_when_present(fixture_html):
    html = fixture_html("track_trace_ok.html")
    result = parse_eta(html)
    assert result["status"] == "ok"
    assert result["data"]["eta"] == "2026-05-03 14:00 KST"
    assert result["data"]["port"] == "Busan, KR"


def test_returns_failed_when_not_found(fixture_html):
    html = fixture_html("track_trace_notfound.html")
    result = parse_eta(html)
    assert result["status"] == "failed"
    assert result["reason"] == "not_found"
```

- [ ] **Step 3: Run test — expect ImportError**

Run: `pytest tests/crawler/test_track_trace_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: bl_tracker.crawler.track_trace`.

- [ ] **Step 4: Write `track_trace.py` (parser + fetch + CLI)**

`src/bl_tracker/crawler/track_trace.py`:
```python
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup  # not yet in deps — add it

from ._browser import browser_context, stealth_page

URL = "https://www.track-trace.com/bol"


def parse_eta(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("div.error"):
        return {"status": "failed", "reason": "not_found"}
    eta_el = soup.select_one('[data-field="eta"]')
    port_el = soup.select_one('[data-field="port"]')
    if not eta_el or not eta_el.get_text(strip=True):
        return {"status": "failed", "reason": "selector_miss"}
    return {
        "status": "ok",
        "data": {
            "eta": eta_el.get_text(strip=True),
            "port": port_el.get_text(strip=True) if port_el else None,
        },
    }


async def fetch_eta(bl_no: str, headless: bool = True) -> dict[str, Any]:
    async with browser_context(headless=headless) as ctx:
        page = await stealth_page(ctx)
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
            await page.fill('input[name="number"], input[type="search"]', bl_no)
            await page.keyboard.press("Enter")
            await page.wait_for_load_state("networkidle", timeout=30_000)
            html = await page.content()
        except Exception as e:
            return {
                "status": "failed",
                "reason": f"playwright_error: {type(e).__name__}: {e}",
                "fetched_at": datetime.utcnow().isoformat() + "Z",
            }
    parsed = parse_eta(html)
    parsed["fetched_at"] = datetime.utcnow().isoformat() + "Z"
    parsed["bl_no"] = bl_no
    return parsed


def main():
    p = argparse.ArgumentParser(description="Fetch ETA from track-trace.com")
    p.add_argument("bl_no")
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()
    result = asyncio.run(fetch_eta(args.bl_no, headless=not args.headed))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add `beautifulsoup4` to deps and reinstall**

Edit `pyproject.toml` — add `"beautifulsoup4>=4.12"` to `dependencies`.

Run: `pip install -e ".[dev]"`

- [ ] **Step 6: Run parser tests — expect PASS**

Run: `pytest tests/crawler/test_track_trace_parser.py -v`
Expected: 2 passed.

- [ ] **Step 7: Smoke run CLI (offline-safe — should reach the site or fail cleanly)**

Run: `python -m bl_tracker.crawler.track_trace TEST123 --headed`
Expected: JSON output with `status` field. (Real BL numbers tested by user later.)

- [ ] **Step 8: Commit**

```bash
git add tests/conftest.py tests/__init__.py tests/fixtures/ tests/crawler/ \
  src/bl_tracker/crawler/track_trace.py pyproject.toml
git commit -m "feat(crawler): track-trace ETA crawler with CLI + parser tests"
```

---

### Task 4: vesselfinder.com crawler (parser + fetch + CLI)

**Files:**
- Create: `tests/fixtures/vesselfinder_ok.html`
- Create: `tests/fixtures/vesselfinder_notfound.html`
- Create: `tests/crawler/test_vesselfinder_parser.py`
- Create: `src/bl_tracker/crawler/vesselfinder.py`

- [ ] **Step 1: Write fixtures**

`tests/fixtures/vesselfinder_ok.html`:
```html
<!doctype html>
<html><body>
<div id="djson"
     data-lat="35.0921"
     data-lon="129.0756"
     data-area="East China Sea"
     data-vessel="MV TEST"></div>
</body></html>
```

`tests/fixtures/vesselfinder_notfound.html`:
```html
<!doctype html>
<html><body>
<div class="no-results">No vessels found</div>
</body></html>
```

- [ ] **Step 2: Write failing parser tests**

`tests/crawler/test_vesselfinder_parser.py`:
```python
from bl_tracker.crawler.vesselfinder import parse_location


def test_parses_lat_lon_area(fixture_html):
    html = fixture_html("vesselfinder_ok.html")
    r = parse_location(html)
    assert r["status"] == "ok"
    assert abs(r["data"]["lat"] - 35.0921) < 1e-6
    assert abs(r["data"]["lon"] - 129.0756) < 1e-6
    assert r["data"]["area"] == "East China Sea"


def test_not_found(fixture_html):
    html = fixture_html("vesselfinder_notfound.html")
    r = parse_location(html)
    assert r["status"] == "failed"
    assert r["reason"] == "not_found"
```

- [ ] **Step 3: Run — expect ImportError**

Run: `pytest tests/crawler/test_vesselfinder_parser.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Write `vesselfinder.py`**

```python
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from ._browser import browser_context, stealth_page

SEARCH_URL = "https://www.vesselfinder.com/vessels?name={imo}"


def parse_location(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("div.no-results"):
        return {"status": "failed", "reason": "not_found"}
    el = soup.select_one("#djson")
    if not el:
        return {"status": "failed", "reason": "selector_miss"}
    try:
        lat = float(el.get("data-lat"))
        lon = float(el.get("data-lon"))
    except (TypeError, ValueError):
        return {"status": "failed", "reason": "bad_coords"}
    return {
        "status": "ok",
        "data": {
            "lat": lat,
            "lon": lon,
            "area": el.get("data-area") or None,
            "vessel": el.get("data-vessel") or None,
        },
    }


async def fetch_location(imo: str, headless: bool = True) -> dict[str, Any]:
    async with browser_context(headless=headless) as ctx:
        page = await stealth_page(ctx)
        try:
            await page.goto(SEARCH_URL.format(imo=imo),
                            wait_until="domcontentloaded", timeout=30_000)
            # site sometimes redirects to vessel detail page automatically
            await page.wait_for_load_state("networkidle", timeout=30_000)
            html = await page.content()
        except Exception as e:
            return {
                "status": "failed",
                "reason": f"playwright_error: {type(e).__name__}: {e}",
                "fetched_at": datetime.utcnow().isoformat() + "Z",
            }
    parsed = parse_location(html)
    parsed["fetched_at"] = datetime.utcnow().isoformat() + "Z"
    parsed["imo"] = imo
    return parsed


def main():
    p = argparse.ArgumentParser(description="Fetch vessel location from vesselfinder.com")
    p.add_argument("imo")
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()
    result = asyncio.run(fetch_location(args.imo, headless=not args.headed))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run parser tests — expect PASS**

Run: `pytest tests/crawler/test_vesselfinder_parser.py -v`
Expected: 2 passed.

- [ ] **Step 6: Smoke CLI**

Run: `python -m bl_tracker.crawler.vesselfinder 9999999 --headed`
Expected: JSON output.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/vesselfinder_ok.html tests/fixtures/vesselfinder_notfound.html \
  tests/crawler/test_vesselfinder_parser.py src/bl_tracker/crawler/vesselfinder.py
git commit -m "feat(crawler): vesselfinder location crawler with CLI + parser tests"
```

---

### **🛑 USER CHECKPOINT — Live crawler test**

After Task 4, **stop and notify the user**. The user will run:

```
python -m bl_tracker.crawler.track_trace <real_BL_no> --headed
python -m bl_tracker.crawler.vesselfinder <real_IMO> --headed
```

Possible outcomes:

1. **Both succeed** → continue to Phase 3.
2. **Selectors miss** → capture the real HTML, replace `tests/fixtures/*.html`, adjust `parse_*` functions, and re-run parser tests. The fetch wrappers (`fetch_eta`, `fetch_location`) may also need updated form selectors / wait conditions.
3. **Bot challenge / CAPTCHA on track-trace** → switch to `--headed` default, increase waits, add referrer; if still blocked, escalate to user (out of scope for this plan).
4. **vesselfinder location text vs reverse-geocode comparison** → with real coords from a few IMOs, decide whether `data-area` text alone is sufficient or whether reverse geocoding is needed. Record decision in spec section 6.

Resume Phase 3 only after explicit user approval.

---

## Phase 3 — Database

### Task 5: Schema + connection

**Files:**
- Create: `src/bl_tracker/db/__init__.py` (empty)
- Create: `src/bl_tracker/db/schema.sql`
- Create: `src/bl_tracker/db/connection.py`

- [ ] **Step 1: Write `schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS shipments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bl_no           TEXT UNIQUE NOT NULL,
    imo_no          TEXT,
    eta             TEXT,
    eta_prev_kst    TEXT,
    eta_changed     INTEGER NOT NULL DEFAULT 0,
    location        TEXT,
    lat             REAL,
    lon             REAL,
    bl_refreshed_at TEXT,
    loc_refreshed_at TEXT,
    memo            TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eta_snapshots (
    shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    kst_date    TEXT NOT NULL,
    eta         TEXT,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (shipment_id, kst_date)
);

CREATE INDEX IF NOT EXISTS idx_shipments_bl ON shipments(bl_no);
```

- [ ] **Step 2: Write `connection.py`**

```python
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from bl_tracker.config import db_path

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def init(path: Path | None = None) -> Path:
    p = path or db_path()
    with sqlite3.connect(p) as conn:
        conn.executescript(_SCHEMA)
        conn.execute("PRAGMA foreign_keys = ON")
    return p


@contextmanager
def connect(path: Path | None = None):
    p = path or db_path()
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

- [ ] **Step 3: Commit**

```bash
git add src/bl_tracker/db/
git commit -m "feat(db): sqlite schema + connection helper"
```

---

### Task 6: Repository layer

**Files:**
- Create: `tests/db/__init__.py`, `tests/db/test_repo.py`
- Create: `src/bl_tracker/db/repo.py`

- [ ] **Step 1: Write failing tests**

`tests/db/test_repo.py`:
```python
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
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/db/test_repo.py -v`
Expected: ImportError on `repo`.

- [ ] **Step 3: Write `repo.py`**

```python
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
        return get_shipment(db, cur.lastrowid)


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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/db/ -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/db/ src/bl_tracker/db/repo.py
git commit -m "feat(db): repository CRUD + eta snapshot upsert"
```

---

## Phase 4 — Refresh Service (KST compare)

### Task 7: Refresh service

**Files:**
- Create: `tests/services/__init__.py`, `tests/services/test_refresh.py`
- Create: `src/bl_tracker/services/__init__.py` (empty)
- Create: `src/bl_tracker/services/refresh.py`

- [ ] **Step 1: Write failing tests**

`tests/services/test_refresh.py`:
```python
import tempfile
from pathlib import Path
from datetime import datetime
import pytest

from bl_tracker.db import connection, repo
from bl_tracker.services import refresh


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        connection.init(p)
        yield p


async def fake_eta_ok(bl):
    return {"status": "ok", "data": {"eta": "2026-05-03 14:00 KST", "port": "Busan"},
            "fetched_at": "2026-04-27T01:00:00Z", "bl_no": bl}


async def fake_eta_failed(bl):
    return {"status": "failed", "reason": "not_found",
            "fetched_at": "2026-04-27T01:00:00Z", "bl_no": bl}


async def fake_loc_ok(imo):
    return {"status": "ok", "data": {"lat": 35.1, "lon": 129.0,
            "area": "Off Busan", "vessel": "MV TEST"},
            "fetched_at": "2026-04-27T01:00:00Z", "imo": imo}


async def test_refresh_bl_marks_changed_when_yesterday_differs(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    # plant yesterday snapshot
    yesterday = refresh._kst_today_minus(1)
    repo.upsert_eta_snapshot(db, s["id"], yesterday, "OLD-ETA", "2026-04-26T...Z")
    monkeypatch.setattr(refresh, "_fetch_eta", fake_eta_ok)
    out = await refresh.refresh_bl(db, s["id"])
    assert out["status"] == "ok"
    fresh = repo.get_shipment(db, s["id"])
    assert fresh["eta"] == "2026-05-03 14:00 KST"
    assert fresh["eta_prev_kst"] == "OLD-ETA"
    assert fresh["eta_changed"] == 1


async def test_refresh_bl_no_yesterday_means_not_changed(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    monkeypatch.setattr(refresh, "_fetch_eta", fake_eta_ok)
    await refresh.refresh_bl(db, s["id"])
    fresh = repo.get_shipment(db, s["id"])
    assert fresh["eta_changed"] == 0
    assert fresh["eta_prev_kst"] is None


async def test_refresh_bl_failed_keeps_previous(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no=None)
    repo.update_shipment(db, s["id"], eta="KEEP")
    monkeypatch.setattr(refresh, "_fetch_eta", fake_eta_failed)
    out = await refresh.refresh_bl(db, s["id"])
    assert out["status"] == "failed"
    fresh = repo.get_shipment(db, s["id"])
    assert fresh["eta"] == "KEEP"


async def test_refresh_loc_writes_lat_lon_area(db, monkeypatch):
    s = repo.create_shipment(db, bl_no="BL1", imo_no="9999999")
    monkeypatch.setattr(refresh, "_fetch_location", fake_loc_ok)
    await refresh.refresh_loc(db, s["id"])
    fresh = repo.get_shipment(db, s["id"])
    assert abs(fresh["lat"] - 35.1) < 1e-6
    assert fresh["location"] == "Off Busan"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/services/test_refresh.py -v`
Expected: ImportError on `refresh`.

- [ ] **Step 3: Write `refresh.py`**

```python
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from bl_tracker.config import KST
from bl_tracker.crawler import track_trace as tt, vesselfinder as vf
from bl_tracker.db import repo


# Indirected so tests can monkeypatch.
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
    repo.update_shipment(
        db, shipment_id,
        lat=d["lat"], lon=d["lon"],
        location=d.get("area"),
        loc_refreshed_at=now_iso,
    )
    return {"status": "ok", "lat": d["lat"], "lon": d["lon"], "area": d.get("area")}


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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/services/test_refresh.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/services/ src/bl_tracker/services/__init__.py src/bl_tracker/services/refresh.py
git commit -m "feat(services): refresh BL/loc with KST date-based change detection"
```

---

## Phase 5 — Excel Import / Export

### Task 8: Excel service

**Files:**
- Create: `tests/services/test_excel.py`
- Create: `src/bl_tracker/services/excel.py`

- [ ] **Step 1: Write failing tests**

`tests/services/test_excel.py`:
```python
import tempfile
from pathlib import Path
import pytest
from openpyxl import Workbook, load_workbook
from bl_tracker.db import connection, repo
from bl_tracker.services import excel


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        connection.init(p)
        yield p


def make_xlsx(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["BL번호", "IMO번호", "ETA", "화물위치"])
    for r in rows:
        ws.append(r)
    out = tmp_path / "in.xlsx"
    wb.save(out)
    return out


def test_import_creates_rows(tmp_path, db):
    f = make_xlsx(tmp_path, [["BL1", "1234567", "ETA-A", "Off Busan"],
                             ["BL2", "7654321", "ETA-B", "ECS"]])
    n = excel.import_xlsx(db, f)
    assert n == 2
    assert len(repo.list_shipments(db)) == 2


def test_import_upserts_on_bl(tmp_path, db):
    repo.create_shipment(db, bl_no="BL1", imo_no="OLD")
    f = make_xlsx(tmp_path, [["BL1", "NEW", "", ""]])
    excel.import_xlsx(db, f)
    s = [r for r in repo.list_shipments(db) if r["bl_no"] == "BL1"][0]
    assert s["imo_no"] == "NEW"
    assert len(repo.list_shipments(db)) == 1


def test_export_roundtrip(tmp_path, db):
    repo.create_shipment(db, bl_no="BL1", imo_no="111")
    out = tmp_path / "out.xlsx"
    excel.export_xlsx(db, out)
    wb = load_workbook(out)
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert headers[:4] == ["BL번호", "IMO번호", "ETA", "화물위치"]
    assert ws.cell(row=2, column=1).value == "BL1"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/services/test_excel.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `excel.py`**

```python
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
    # Allow either Korean or simple positional matching of first 2 cols
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/services/test_excel.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/services/test_excel.py src/bl_tracker/services/excel.py
git commit -m "feat(services): excel import/export"
```

---

## Phase 6 — API

### Task 9: FastAPI app + shipments CRUD

**Files:**
- Create: `tests/api/__init__.py`, `tests/api/test_shipments.py`
- Create: `src/bl_tracker/api/__init__.py` (empty)
- Create: `src/bl_tracker/api/app.py`
- Create: `src/bl_tracker/api/shipments.py`

- [ ] **Step 1: Write failing tests**

`tests/api/test_shipments.py`:
```python
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
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/api/test_shipments.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app.py`**

```python
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
```

- [ ] **Step 4: Write `shipments.py`**

```python
from __future__ import annotations
import sqlite3
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bl_tracker.db import repo

router = APIRouter()


class ShipmentIn(BaseModel):
    bl_no: str
    imo_no: str | None = None
    memo: str | None = None


class ShipmentPatch(BaseModel):
    bl_no: str | None = None
    imo_no: str | None = None
    memo: str | None = None


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
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `pytest tests/api/test_shipments.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/api/ src/bl_tracker/api/
git commit -m "feat(api): shipments CRUD endpoints"
```

---

### Task 10: Refresh routes (single + bulk SSE)

**Files:**
- Create: `tests/api/test_refresh.py`
- Create: `src/bl_tracker/api/refresh.py`
- Modify: `src/bl_tracker/api/app.py` (include router)

- [ ] **Step 1: Write failing tests**

`tests/api/test_refresh.py`:
```python
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from bl_tracker.db import connection, repo
from bl_tracker.api.app import build_app
from bl_tracker.services import refresh as refresh_svc


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        connection.init(p)

        async def fake_eta(bl):
            return {"status": "ok", "data": {"eta": f"ETA-{bl}", "port": "Busan"},
                    "fetched_at": "2026-04-27T01:00:00Z", "bl_no": bl}

        async def fake_loc(imo):
            return {"status": "ok",
                    "data": {"lat": 1.0, "lon": 2.0, "area": "X", "vessel": "v"},
                    "fetched_at": "2026-04-27T01:00:00Z", "imo": imo}

        monkeypatch.setattr(refresh_svc, "_fetch_eta", fake_eta)
        monkeypatch.setattr(refresh_svc, "_fetch_location", fake_loc)

        app = build_app(db=p)
        with TestClient(app) as c:
            c.db_path = p
            yield c


def test_single_bl_refresh(client):
    s = repo.create_shipment(client.db_path, bl_no="BL1", imo_no="1")
    r = client.post(f"/shipments/{s['id']}/refresh-bl")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_single_loc_refresh(client):
    s = repo.create_shipment(client.db_path, bl_no="BL1", imo_no="1")
    r = client.post(f"/shipments/{s['id']}/refresh-loc")
    assert r.status_code == 200


def test_bulk_sse_emits_progress(client):
    a = repo.create_shipment(client.db_path, bl_no="A", imo_no="1")
    b = repo.create_shipment(client.db_path, bl_no="B", imo_no="2")
    with client.stream("POST", "/shipments/refresh-bulk",
                       json={"ids": [a["id"], b["id"]],
                             "targets": ["bl", "loc"]}) as r:
        events = [line for line in r.iter_lines() if line.startswith("data:")]
    assert len(events) >= 4  # 2 ids x 2 targets
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/api/test_refresh.py -v`
Expected: 404 / module missing.

- [ ] **Step 3: Write `api/refresh.py`**

```python
from __future__ import annotations
import asyncio
import json
from typing import Literal
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
    ids: list[int]
    targets: list[Literal["bl", "loc"]]


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
```

- [ ] **Step 4: Wire router in `app.py`**

Edit `src/bl_tracker/api/app.py` — add import + include:
```python
from .refresh import router as refresh_router
# inside build_app, after shipments_router include:
app.include_router(refresh_router)
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `pytest tests/api/ -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/api/test_refresh.py src/bl_tracker/api/refresh.py src/bl_tracker/api/app.py
git commit -m "feat(api): single + bulk refresh with SSE progress (concurrency 3)"
```

---

### Task 11: Excel routes

**Files:**
- Create: `src/bl_tracker/api/excel.py`
- Modify: `src/bl_tracker/api/app.py`
- Modify: `tests/api/test_shipments.py` (add tests)

- [ ] **Step 1: Add failing tests** (append to `tests/api/test_shipments.py`)

```python
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
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/api/test_shipments.py::test_excel_import_export_roundtrip -v`
Expected: 404.

- [ ] **Step 3: Write `api/excel.py`**

```python
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
```

- [ ] **Step 4: Wire router in `app.py`**

Add to `build_app`:
```python
from .excel import router as excel_router
# ...
app.include_router(excel_router)
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `pytest tests/api/ -v`

- [ ] **Step 6: Commit**

```bash
git add tests/api/test_shipments.py src/bl_tracker/api/excel.py src/bl_tracker/api/app.py
git commit -m "feat(api): excel import/export routes"
```

---

## Phase 7 — Frontend

### Task 12: Static HTML + JS

**Files:**
- Create: `src/bl_tracker/web/index.html`
- Create: `src/bl_tracker/web/app.js`
- Modify: `src/bl_tracker/api/app.py` (mount static + index route)

- [ ] **Step 1: Write `index.html`**

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>BL Tracker</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 16px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid #ddd; padding: 6px 8px; }
  th { background: #f5f5f5; text-align: left; }
  tr.changed { background: #ffe6e6; }
  .toolbar { margin-bottom: 12px; display: flex; gap: 8px; align-items: center; }
  button { padding: 4px 10px; cursor: pointer; }
  #progress { font-size: 12px; color: #555; }
</style>
</head>
<body>
<h1>BL Tracker</h1>
<div class="toolbar">
  <button id="btn-add">행 추가</button>
  <button id="btn-refresh-selected">선택 새로고침</button>
  <button id="btn-refresh-all">전체 새로고침</button>
  <input type="file" id="file-import" accept=".xlsx" hidden>
  <button id="btn-import">엑셀 업로드</button>
  <button id="btn-export">엑셀 내보내기</button>
  <span id="progress"></span>
</div>
<table id="t">
  <thead>
    <tr>
      <th><input type="checkbox" id="chk-all"></th>
      <th>BL번호</th><th>IMO</th><th>ETA</th><th>이전 ETA</th>
      <th>위치</th><th>위경도</th><th>BL갱신</th><th>위치갱신</th>
      <th>메모</th><th>액션</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>
<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app.js`**

```javascript
const $ = (q) => document.querySelector(q);
const tbody = $("#t tbody");
const progress = $("#progress");

async function load() {
  const r = await fetch("/shipments");
  const rows = await r.json();
  tbody.innerHTML = "";
  for (const s of rows) tbody.appendChild(rowEl(s));
}

function rowEl(s) {
  const tr = document.createElement("tr");
  if (s.eta_changed) tr.classList.add("changed");
  tr.dataset.id = s.id;
  tr.innerHTML = `
    <td><input type="checkbox" class="sel"></td>
    <td contenteditable data-f="bl_no">${s.bl_no ?? ""}</td>
    <td contenteditable data-f="imo_no">${s.imo_no ?? ""}</td>
    <td>${s.eta ?? ""}</td>
    <td>${s.eta_prev_kst ?? ""}</td>
    <td>${s.location ?? ""}</td>
    <td>${s.lat != null ? s.lat.toFixed(4) + ", " + s.lon.toFixed(4) : ""}</td>
    <td>${s.bl_refreshed_at ?? ""}</td>
    <td>${s.loc_refreshed_at ?? ""}</td>
    <td contenteditable data-f="memo">${s.memo ?? ""}</td>
    <td>
      <button class="bl">BL새로고침</button>
      <button class="loc">위치새로고침</button>
      <button class="del">삭제</button>
    </td>`;
  tr.querySelector(".bl").onclick = () => single(s.id, "bl");
  tr.querySelector(".loc").onclick = () => single(s.id, "loc");
  tr.querySelector(".del").onclick = async () => {
    await fetch(`/shipments/${s.id}`, { method: "DELETE" });
    load();
  };
  tr.querySelectorAll("[contenteditable]").forEach(el => {
    el.addEventListener("blur", async () => {
      const body = { [el.dataset.f]: el.textContent.trim() };
      await fetch(`/shipments/${s.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    });
  });
  return tr;
}

async function single(id, target) {
  progress.textContent = `${id} ${target} 갱신중…`;
  const r = await fetch(`/shipments/${id}/refresh-${target}`, { method: "POST" });
  const j = await r.json();
  progress.textContent = `${id} ${target}: ${j.status}`;
  load();
}

function selectedIds() {
  return [...tbody.querySelectorAll("tr")]
    .filter(tr => tr.querySelector(".sel").checked)
    .map(tr => Number(tr.dataset.id));
}

async function bulk(ids) {
  if (!ids.length) { progress.textContent = "선택 없음"; return; }
  progress.textContent = `0/${ids.length * 2}`;
  const resp = await fetch("/shipments/refresh-bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, targets: ["bl", "loc"] }),
  });
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value);
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) {
      if (line.startsWith("data:")) {
        try {
          const ev = JSON.parse(line.slice(5).trim());
          progress.textContent = `${ev.done}/${ev.total}`;
        } catch {}
      }
    }
  }
  load();
  progress.textContent += " 완료";
}

$("#btn-refresh-selected").onclick = () => bulk(selectedIds());
$("#btn-refresh-all").onclick = () => {
  const ids = [...tbody.querySelectorAll("tr")].map(tr => Number(tr.dataset.id));
  bulk(ids);
};
$("#chk-all").onchange = (e) => {
  tbody.querySelectorAll(".sel").forEach(c => c.checked = e.target.checked);
};
$("#btn-add").onclick = async () => {
  const bl = prompt("BL 번호");
  if (!bl) return;
  const imo = prompt("IMO 번호 (선택)") || null;
  const r = await fetch("/shipments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bl_no: bl, imo_no: imo }),
  });
  if (r.status === 409) alert("중복된 BL");
  load();
};
$("#btn-import").onclick = () => $("#file-import").click();
$("#file-import").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch("/import/excel", { method: "POST", body: fd });
  const j = await r.json();
  progress.textContent = `${j.imported}건 import`;
  load();
};
$("#btn-export").onclick = () => { window.location = "/export/excel"; };

load();
```

- [ ] **Step 3: Mount static + index in `app.py`**

Edit `src/bl_tracker/api/app.py` `build_app`:
```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import importlib.resources as ir

# inside build_app, after include_routers:
web_dir = Path(__file__).parent.parent / "web"
app.mount("/static", StaticFiles(directory=web_dir), name="static")

@app.get("/")
def index():
    return FileResponse(web_dir / "index.html")
```

- [ ] **Step 4: Manual smoke**

Run:
```bash
python -m bl_tracker
```
Open `http://localhost:7777`. Verify: add row, BL refresh button calls (will fail without real data — OK), import xlsx, export xlsx.

- [ ] **Step 5: Commit**

```bash
git add src/bl_tracker/web/ src/bl_tracker/api/app.py
git commit -m "feat(web): table UI with refresh buttons + SSE progress"
```

---

## Phase 8 — Entry Point + Packaging

### Task 13: `__main__` entry point

**Files:**
- Create: `src/bl_tracker/__main__.py`

- [ ] **Step 1: Write entry point**

```python
from __future__ import annotations
import threading
import time
import webbrowser
import uvicorn

from bl_tracker.config import HOST, PORT
from bl_tracker.db import connection
from bl_tracker.api.app import app


def _open_browser():
    time.sleep(1.0)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main():
    connection.init()  # ensure schema exists
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke run**

Run: `python -m bl_tracker`
Expected: browser opens to `http://127.0.0.1:7777` showing the table.

- [ ] **Step 3: Commit**

```bash
git add src/bl_tracker/__main__.py
git commit -m "feat: app entry point with browser auto-open"
```

---

### Task 14: PyInstaller spec

**Files:**
- Create: `packaging/bl_tracker.spec`

- [ ] **Step 1: Write spec**

```python
# packaging/bl_tracker.spec
# Build:  pyinstaller packaging/bl_tracker.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = []
datas += collect_data_files("playwright")  # Playwright JS bridge
datas += [("../src/bl_tracker/web", "bl_tracker/web"),
          ("../src/bl_tracker/db/schema.sql", "bl_tracker/db")]

hidden = []
hidden += collect_submodules("uvicorn")
hidden += collect_submodules("fastapi")
hidden += ["sse_starlette", "sse_starlette.sse"]

a = Analysis(
    ["../src/bl_tracker/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="bl-tracker",
    debug=False, strip=False, upx=False,
    console=True,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False,
    name="bl-tracker",
)
```

- [ ] **Step 2: Note on Playwright Chromium**

PyInstaller cannot easily bundle the Chromium binaries. Strategy: on first run, the app calls `playwright install chromium` if the browser is not found. Add to `__main__.main()`:

```python
def _ensure_chromium():
    import subprocess, sys
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.executable_path  # raises if missing
    except Exception:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)


def main():
    _ensure_chromium()
    connection.init()
    ...
```

Apply this edit to `src/bl_tracker/__main__.py`.

- [ ] **Step 3: Build (on Windows host — note for user)**

Build is performed on Windows. On macOS dev box, just confirm spec parses:

Run: `pyinstaller --noconfirm --clean packaging/bl_tracker.spec` (will produce a macOS bundle for local sanity; final exe on Windows).

Expected: `dist/bl-tracker/bl-tracker` (or `.exe` on Windows) created. Run it; browser opens.

- [ ] **Step 4: Commit**

```bash
git add packaging/bl_tracker.spec src/bl_tracker/__main__.py
git commit -m "build: pyinstaller spec + first-run chromium install"
```

---

## Phase 9 — Final Smoke

### Task 15: End-to-end manual smoke + push

- [ ] **Step 1: Full test suite**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 2: Manual flow**

1. Run `python -m bl_tracker`. Browser opens.
2. 행 추가 (BL=`<real BL>`, IMO=`<real IMO>`).
3. BL새로고침 → ETA 표시.
4. 위치새로고침 → location/lat/lon 표시.
5. 행 추가 2개 더 → 전체 새로고침 → 진행률 반영.
6. 엑셀 내보내기 → xlsx 다운로드.
7. 새 폴더에 동일 xlsx → 엑셀 업로드 → 행 복원.

- [ ] **Step 3: Push**

```bash
git push
```

---

## Spec Coverage Self-Review

| Spec section | Tasks |
|---|---|
| 3. 사용자 흐름 (행 추가/편집/삭제, 단건/선택/전체 새로고침, ETA 강조, import/export) | 9, 10, 11, 12 |
| 4. 아키텍처 (FastAPI + SQLite + Playwright + 정적 HTML + PyInstaller) | 1, 5, 9, 12, 14 |
| 4. crawler/ CLI 단독 실행 | 3, 4 |
| 4. 127.0.0.1:7777 + 자동 브라우저 오픈 | 13 |
| 5. shipments + eta_snapshots 스키마 | 5 |
| 5. KST 어제 vs 오늘 ETA 비교 | 7 |
| 6. 위치 A/B 프로토타입 (parser는 area + lat/lon 둘 다 반환) | 4, 검증 user checkpoint |
| 7. 동시성 3 + SSE 진행률 | 7, 10, 12 |
| 8. 에러 처리 (failed 시 마지막값 유지, ⚠️ 표시) | 7 (keeps prev), 12 (UI) |
| 9. 테스트 (파서 픽스처, repo, 서비스, API) | 3, 4, 6, 7, 8, 9, 10, 11 |
| 10. 단계 (Spike 우선) | Phase 2 + checkpoint |
