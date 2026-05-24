"""FastAPI application for music deduplication web interface."""

from __future__ import annotations

import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai_dedupe import ai_find_duplicate_groups
from .dedupe import default_backup_dir, default_rule_states, find_duplicate_groups, human_size
from .models import AudioTrack, DuplicateGroup
from .scanner import list_available_roots, scan_audio_files


# ---------------------------------------------------------------------------
# Data classes for application state
# ---------------------------------------------------------------------------


@dataclass
class ScanTaskState:
    """Tracks the state of a single background scan task."""

    task_id: str
    root: str
    status: str = "pending"  # pending | scanning | done | error | stopped
    progress_message: str = ""
    processed_files: int = 0
    tracks: list[AudioTrack] = field(default_factory=list)
    groups: list[DuplicateGroup] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    error: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    algorithm: str = "builtin"
    ai_url: str = ""
    ai_key: str = ""
    ai_model: str = ""


@dataclass
class ExecuteTaskState:
    """Tracks the state of a single background execute task."""

    task_id: str
    status: str = "pending"  # pending | executing | done | error | stopped
    progress_message: str = ""
    moved_count: int = 0
    total_count: int = 0
    backup_dir: str = ""
    errors: list[str] = field(default_factory=list)
    error: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


@dataclass
class AppState:
    """Global application state shared across requests."""

    tasks: dict[str, ScanTaskState] = field(default_factory=dict)
    execute_tasks: dict[str, ExecuteTaskState] = field(default_factory=dict)
    tracks: list[AudioTrack] = field(default_factory=list)
    groups: list[DuplicateGroup] = field(default_factory=list)
    scan_root: str = ""
    rule_states: list = field(default_factory=default_rule_states)
    lock: threading.Lock = field(default_factory=threading.Lock)


# Module-level state (mutable singleton)
APP_STATE = AppState()


def reset_state() -> None:
    """Reset module-level state. Intended for test isolation."""
    APP_STATE.tasks.clear()
    APP_STATE.execute_tasks.clear()
    APP_STATE.tracks.clear()
    APP_STATE.groups.clear()
    APP_STATE.scan_root = ""
    APP_STATE.rule_states = default_rule_states()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _group_id(index: int, group: DuplicateGroup) -> str:
    """Build a human-friendly, URL-safe group identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", group.key.lower()).strip("-")
    return f"group-{index}-{slug}"


def _group_to_dict(index: int, group: DuplicateGroup) -> dict:
    """Serialise a DuplicateGroup to a JSON-friendly dict."""
    return {
        "id": _group_id(index, group),
        "key": group.key,
        "tracks": [_track_to_dict(t) for t in group.tracks],
        "keep_track": _track_to_dict(group.keep_track),
        "duplicate_tracks": [_track_to_dict(t) for t in group.duplicate_tracks],
        "reclaimable_bytes": group.reclaimable_bytes,
        "reclaimable_display": human_size(group.reclaimable_bytes),
    }


def _track_to_dict(track: AudioTrack) -> dict:
    """Serialise an AudioTrack to a JSON-friendly dict."""
    return {
        "path": str(track.path),
        "root": str(track.root),
        "extension": track.extension,
        "size_bytes": track.size_bytes,
        "size_display": human_size(track.size_bytes),
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "bitrate_kbps": track.bitrate_kbps,
        "duration_seconds": track.duration_seconds,
        "has_cover": track.has_cover,
        "metadata_source": track.metadata_source,
        "year": track.year,
        "genre": track.genre,
        "track_number": track.track_number,
        "format_info": track.format_info,
        "warnings": track.warnings,
    }


# ---------------------------------------------------------------------------
# Background scan worker
# ---------------------------------------------------------------------------


def _run_scan(task: ScanTaskState) -> None:
    """Execute a scan in a background thread, updating task state."""
    task.status = "scanning"
    task.log.append(f"开始扫描 {task.root}")

    def progress(msg: str) -> None:
        task.progress_message = msg
        task.log.append(msg)

    try:
        root_path = Path(task.root)
        task.tracks = scan_audio_files(root_path, progress=progress, stop_event=task.stop_event)
        task.processed_files = len(task.tracks)

        with APP_STATE.lock:
            APP_STATE.tracks = task.tracks
            APP_STATE.scan_root = task.root

            if task.algorithm == "ai" and task.ai_url and task.ai_key:
                progress("使用 AI 算法进行去重分析...")
                APP_STATE.groups = ai_find_duplicate_groups(
                    task.tracks,
                    APP_STATE.rule_states,
                    api_url=task.ai_url,
                    api_key=task.ai_key,
                    model=task.ai_model or "gpt-4o-mini",
                    progress=progress,
                )
            else:
                APP_STATE.groups = find_duplicate_groups(task.tracks, APP_STATE.rule_states)
            task.groups = list(APP_STATE.groups)

        if task.stop_event.is_set():
            task.status = "stopped"
        else:
            task.status = "done"
        task.log.append(f"扫描完成，发现 {len(task.groups)} 组重复。")
    except Exception as exc:
        task.status = "error"
        task.error = str(exc)
        task.log.append(f"扫描出错: {exc}")


# ---------------------------------------------------------------------------
# Background execute worker
# ---------------------------------------------------------------------------


def _run_execute(task: ExecuteTaskState) -> None:
    """Execute deduplication in a background thread, updating task state."""
    task.status = "executing"
    task.progress_message = "准备执行去重..."

    try:
        with APP_STATE.lock:
            groups = list(APP_STATE.groups)

        if not groups:
            task.status = "error"
            task.error = "no groups to process"
            task.progress_message = "没有可处理的分组"
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = default_backup_dir() / timestamp
        backup.mkdir(parents=True, exist_ok=True)
        task.backup_dir = str(backup)

        total = sum(len(g.duplicate_tracks) for g in groups)
        task.total_count = total
        moved = 0

        for group in groups:
            for dup in group.duplicate_tracks:
                if task.stop_event.is_set():
                    task.status = "stopped"
                    task.progress_message = f"已停止，已移动 {moved}/{total} 个文件"
                    return
                try:
                    if dup.path.exists():
                        shutil.move(str(dup.path), str(backup / dup.path.name))
                        moved += 1
                        task.moved_count = moved
                        task.progress_message = f"正在移动文件 ({moved}/{total})..."
                except Exception as exc:
                    task.errors.append(f"{dup.path}: {exc}")

        # Remove moved tracks from state
        moved_paths: set[str] = set()
        for g in groups:
            for d in g.duplicate_tracks:
                moved_paths.add(str(d.path))

        with APP_STATE.lock:
            APP_STATE.tracks = [t for t in APP_STATE.tracks if str(t.path) not in moved_paths]
            # Recompute groups from remaining tracks for correctness
            remaining = APP_STATE.tracks
            if remaining:
                APP_STATE.groups = find_duplicate_groups(remaining, APP_STATE.rule_states)
            else:
                APP_STATE.groups = []

        task.progress_message = f"完成，已移动 {moved} 个文件到 {backup}"
        task.status = "done"

    except Exception as exc:
        task.status = "error"
        task.error = str(exc)
        task.progress_message = f"执行出错: {exc}"


# ---------------------------------------------------------------------------
# FastAPI application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="Music Deduplication", version="0.1.0")

    # Mount static files so the frontend can be served
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ---- GET /api/roots ----

    @app.get("/api/roots")
    def get_roots() -> list[str]:
        return list_available_roots()

    # ---- GET /api/browse ----

    @app.get("/api/browse")
    def browse_directory(path: str = "") -> dict:
        """List subdirectories of the given path for directory browsing."""
        if not path:
            return {"path": "", "parent": "", "children": list_available_roots()}
        try:
            target = Path(path)
            if not target.exists() or not target.is_dir():
                return {"path": path, "parent": "", "children": []}
            children = sorted(
                child.name for child in target.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            )
            parent = str(target.parent) if target.parent != target else ""
            return {"path": str(target), "parent": parent, "children": children}
        except (PermissionError, OSError):
            return {"path": path, "parent": "", "children": []}

    # ---- POST /api/scan ----

    @app.post("/api/scan")
    def start_scan(
        root: str,
        algorithm: str = "builtin",
        ai_url: str = "",
        ai_key: str = "",
        ai_model: str = "",
    ) -> dict:
        task_id = uuid.uuid4().hex[:8]
        task = ScanTaskState(
            task_id=task_id,
            root=root,
            algorithm=algorithm,
            ai_url=ai_url,
            ai_key=ai_key,
            ai_model=ai_model,
        )
        APP_STATE.tasks[task_id] = task
        task.thread = threading.Thread(target=_run_scan, args=(task,), daemon=True)
        task.thread.start()
        return {"task_id": task_id}

    # ---- GET /api/scan/{task_id}/status ----

    @app.get("/api/scan/{task_id}/status")
    def scan_status(task_id: str) -> dict:
        task = APP_STATE.tasks.get(task_id)
        if task is None:
            return {"error": "unknown task"}
        return {
            "task_id": task.task_id,
            "root": task.root,
            "status": task.status,
            "progress_message": task.progress_message,
            "processed_files": task.processed_files,
            "groups_found": len(task.groups),
            "log": task.log,
            "error": task.error,
        }

    # ---- POST /api/scan/{task_id}/stop ----

    @app.post("/api/scan/{task_id}/stop")
    def stop_scan(task_id: str) -> dict:
        task = APP_STATE.tasks.get(task_id)
        if task is None:
            return {"error": "unknown task"}
        task.stop_event.set()
        return {"status": "stopping"}

    # ---- GET /api/groups ----

    @app.get("/api/groups")
    def get_groups(search: str = "", artist: str = "") -> dict:
        with APP_STATE.lock:
            groups = list(APP_STATE.groups)
            tracks = list(APP_STATE.tracks)

        # Apply filters
        if search:
            s = search.lower()
            groups = [g for g in groups if s in g.key.lower()]

        if artist:
            a = artist.lower()
            groups = [g for g in groups if any(a in t.artist.lower() for t in g.tracks)]

        # Stats
        total_duplicates = sum(len(g.duplicate_tracks) for g in groups)
        total_reclaimable = sum(g.reclaimable_bytes for g in groups)

        return {
            "groups": [_group_to_dict(i, g) for i, g in enumerate(groups)],
            "stats": {
                "total_tracks": len(tracks),
                "total_groups": len(groups),
                "total_duplicates": total_duplicates,
                "total_reclaimable_bytes": total_reclaimable,
                "total_reclaimable_display": human_size(total_reclaimable),
            },
        }

    # ---- GET /api/groups/{group_id} ----

    @app.get("/api/groups/{group_id}")
    def get_group(group_id: str) -> dict:
        with APP_STATE.lock:
            for i, g in enumerate(APP_STATE.groups):
                if _group_id(i, g) == group_id:
                    return _group_to_dict(i, g)
        return {"error": "group not found"}

    # ---- PUT /api/groups/{group_id}/keep ----

    @app.put("/api/groups/{group_id}/keep")
    def switch_keep(group_id: str, path: str) -> dict:
        with APP_STATE.lock:
            for i, g in enumerate(APP_STATE.groups):
                if _group_id(i, g) == group_id:
                    # Find the new keep track by path
                    target = None
                    for t in g.tracks:
                        if str(t.path) == path:
                            target = t
                            break
                    if target is None:
                        return {"error": "track not found in group"}

                    # Replace keep_track and rebuild duplicate list
                    APP_STATE.groups[i] = DuplicateGroup(
                        key=g.key,
                        tracks=g.tracks,
                        keep_track=target,
                        duplicate_tracks=[t for t in g.tracks if t.path != target.path],
                    )
                    return _group_to_dict(i, APP_STATE.groups[i])
        return {"error": "group not found"}

    # ---- POST /api/execute ----

    @app.post("/api/execute")
    def execute_dedupe() -> dict:
        with APP_STATE.lock:
            groups = list(APP_STATE.groups)

        if not groups:
            return {"error": "no groups to process"}

        task_id = uuid.uuid4().hex[:8]
        total = sum(len(g.duplicate_tracks) for g in groups)
        task = ExecuteTaskState(task_id=task_id, total_count=total)
        APP_STATE.execute_tasks[task_id] = task
        task.thread = threading.Thread(target=_run_execute, args=(task,), daemon=True)
        task.thread.start()
        return {"task_id": task_id}

    # ---- GET /api/execute/{task_id}/status ----

    @app.get("/api/execute/{task_id}/status")
    def execute_status(task_id: str) -> dict:
        task = APP_STATE.execute_tasks.get(task_id)
        if task is None:
            return {"error": "unknown task"}
        return {
            "task_id": task.task_id,
            "status": task.status,
            "progress_message": task.progress_message,
            "moved_count": task.moved_count,
            "total_count": task.total_count,
            "backup_dir": task.backup_dir,
            "errors": task.errors,
        }

    # ---- POST /api/execute/{task_id}/stop ----

    @app.post("/api/execute/{task_id}/stop")
    def stop_execute(task_id: str) -> dict:
        task = APP_STATE.execute_tasks.get(task_id)
        if task is None:
            return {"error": "unknown task"}
        task.stop_event.set()
        return {"status": "stopping"}

    # ---- GET /api/export ----

    @app.get("/api/export")
    def export_report() -> FileResponse:
        with APP_STATE.lock:
            groups = list(APP_STATE.groups)
            tracks = list(APP_STATE.tracks)

        data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "scan_root": APP_STATE.scan_root,
            "total_tracks": len(tracks),
            "total_groups": len(groups),
            "groups": [_group_to_dict(i, g) for i, g in enumerate(groups)],
        }

        export_path = Path(__file__).resolve().parent / "static" / "report.json"
        import json

        export_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return FileResponse(
            path=str(export_path),
            media_type="application/json",
            filename="dedup-report.json",
        )

    # ---- Serve index.html for the root path ----

    @app.get("/")
    def serve_index() -> FileResponse:
        index = _STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return FileResponse(str(_STATIC_DIR / ".placeholder"))

    return app


# Module-level app instance for easy import (e.g. uvicorn music_deduper.server:app)
app = create_app()
