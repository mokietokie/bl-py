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
