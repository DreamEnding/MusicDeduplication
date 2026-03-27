from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn


def _open_browser() -> None:
    time.sleep(1.0)
    webbrowser.open("http://127.0.0.1:8000")


def main() -> int:
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("music_deduper.server:app", host="127.0.0.1", port=8000, reload=False)
    return 0
