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
