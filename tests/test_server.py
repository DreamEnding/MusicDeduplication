"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from music_deduper.models import AudioTrack, DuplicateGroup
from music_deduper.server import APP_STATE, create_app, reset_state


@pytest.fixture(autouse=True)
def _isolate_state():
    """Reset module-level APP_STATE before each test."""
    reset_state()
    yield
    reset_state()


@pytest.fixture()
def client():
    """Return a fresh TestClient with an isolated app."""
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_track(path: str, artist: str = "Artist", title: str = "Song", **kwargs) -> AudioTrack:
    """Create a minimal AudioTrack for testing."""
    defaults = dict(
        root=Path("D:/music"),
        extension=".mp3",
        size_bytes=3000,
        title=title,
        artist=artist,
        album="Album",
        bitrate_kbps=320,
        duration_seconds=200.0,
        has_cover=False,
        metadata_source="test",
    )
    defaults.update(kwargs)
    return AudioTrack(path=Path(path), **defaults)


def _seed_groups():
    """Populate APP_STATE with sample duplicate groups."""
    t1 = _make_track("D:/music/a/Song.mp3", artist="AB", title="Song")
    t2 = _make_track("D:/music/b/Song.mp3", artist="AB", title="Song", size_bytes=5000)
    group = DuplicateGroup(
        key="AB / Song",
        tracks=[t1, t2],
        keep_track=t1,
        duplicate_tracks=[t2],
    )
    APP_STATE.tracks = [t1, t2]
    APP_STATE.groups = [group]
    APP_STATE.scan_root = "D:\\music"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetRoots:
    def test_returns_drive_letters(self, client):
        resp = client.get("/api/roots")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0


class TestGetGroups:
    def test_returns_stats_and_empty_groups_initially(self, client):
        resp = client.get("/api/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert "stats" in data
        assert isinstance(data["groups"], list)
        assert data["stats"]["total_tracks"] == 0
        assert data["stats"]["total_groups"] == 0
        assert data["stats"]["total_duplicates"] == 0

    def test_returns_seeded_groups(self, client):
        _seed_groups()
        resp = client.get("/api/groups")
        data = resp.json()
        assert len(data["groups"]) == 1
        assert data["stats"]["total_tracks"] == 2
        assert data["stats"]["total_groups"] == 1
        assert data["stats"]["total_duplicates"] == 1

    def test_search_filter(self, client):
        _seed_groups()
        resp = client.get("/api/groups", params={"search": "nonexistent"})
        data = resp.json()
        assert len(data["groups"]) == 0

    def test_artist_filter(self, client):
        _seed_groups()
        resp = client.get("/api/groups", params={"artist": "AB"})
        data = resp.json()
        assert len(data["groups"]) == 1


class TestSwitchKeep:
    def test_switches_keep_track(self, client):
        _seed_groups()
        groups_before = client.get("/api/groups").json()["groups"]
        group = groups_before[0]
        group_id = group["id"]

        # The duplicate track path
        dup_path = group["duplicate_tracks"][0]["path"]
        assert group["keep_track"]["path"] != dup_path

        resp = client.put(f"/api/groups/{group_id}/keep", params={"path": dup_path})
        assert resp.status_code == 200
        updated = resp.json()

        # Now the keep track should be the former duplicate
        assert updated["keep_track"]["path"] == dup_path

    def test_switch_to_nonexistent_track(self, client):
        _seed_groups()
        groups = client.get("/api/groups").json()["groups"]
        group_id = groups[0]["id"]

        resp = client.put(f"/api/groups/{group_id}/keep", params={"path": "D:/nonexistent.mp3"})
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_switch_nonexistent_group(self, client):
        resp = client.put("/api/groups/group-999-nonexistent/keep", params={"path": "D:/x.mp3"})
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestExport:
    def test_export_returns_json_file(self, client):
        _seed_groups()
        resp = client.get("/api/export")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        # Check JSON content
        data = json.loads(resp.content)
        assert "exported_at" in data
        assert "total_groups" in data
        assert data["total_groups"] == 1

    def test_export_empty(self, client):
        resp = client.get("/api/export")
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data["total_tracks"] == 0
        assert data["total_groups"] == 0


class TestScanStatus:
    def test_unknown_task_returns_error(self, client):
        resp = client.get("/api/scan/nonexistent/status")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_start_scan_returns_task_id(self, client):
        with patch("music_deduper.server.scan_audio_files", return_value=[]):
            resp = client.post("/api/scan", params={"root": "D:\\music"})
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data


class TestStopScan:
    def test_stop_unknown_task(self, client):
        resp = client.post("/api/scan/nonexistent/stop")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestGetGroup:
    def test_get_existing_group(self, client):
        _seed_groups()
        groups = client.get("/api/groups").json()["groups"]
        group_id = groups[0]["id"]

        resp = client.get(f"/api/groups/{group_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == group_id

    def test_get_nonexistent_group(self, client):
        resp = client.get("/api/groups/group-999-nonexistent")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestExecuteDedupe:
    def test_execute_with_no_groups(self, client):
        resp = client.post("/api/execute")
        assert resp.status_code == 200
        assert "error" in resp.json()
