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
