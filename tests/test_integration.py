"""End-to-end integration test: HTML serving and empty API state."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fastapi.testclient import TestClient

import music_deduper.server as server


def test_html_and_api_bootstrap(monkeypatch) -> None:
    server.reset_state()
    monkeypatch.setattr(server, "list_available_roots", lambda: ["C:\\", "D:\\"])

    client = TestClient(server.create_app())

    # Root serves HTML
    root_response = client.get("/")
    assert root_response.status_code == 200
    assert "text/html" in root_response.headers["content-type"]
    assert "<!doctype html>" in root_response.text.lower()

    # API roots
    roots_response = client.get("/api/roots")
    assert roots_response.status_code == 200
    roots = roots_response.json()
    assert isinstance(roots, list)
    assert "C:\\" in roots

    # Empty groups state
    groups_response = client.get("/api/groups")
    assert groups_response.status_code == 200
    payload = groups_response.json()
    assert payload["stats"]["total_tracks"] == 0
    assert payload["stats"]["total_groups"] == 0
    assert payload["groups"] == []
