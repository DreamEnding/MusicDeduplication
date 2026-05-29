"""FastAPI application for music deduplication web interface."""

from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File as FastAPIFile, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .ai_dedupe import ai_find_duplicate_groups
from .config import get_settings
from .dedupe import default_backup_dir, default_rule_states, find_duplicate_groups, human_size
from .models import AudioTrack, DuplicateGroup
from .audio_metadata import cover_key_for_path, get_cover
from .scanner import list_available_roots, scan_audio_files

# Load settings
settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.log_file, encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


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
    lock: threading.Lock = field(default_factory=threading.Lock)


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
    lock: threading.Lock = field(default_factory=threading.Lock)


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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    """Request model for scan endpoint."""
    root: str
    algorithm: Literal["builtin", "ai"] = "builtin"
    ai_url: Optional[str] = ""
    ai_key: Optional[str] = ""
    ai_model: Optional[str] = ""


class RuleState(BaseModel):
    """Rule state model."""
    key: str
    label: str
    enabled: bool


class RulesUpdateRequest(BaseModel):
    """Request model for rules update endpoint."""
    rules: list[RuleState]


class BatchUpdateRequest(BaseModel):
    """Request model for batch track metadata update."""
    paths: list[str]
    updates: dict[str, str | int | None]


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


def _validate_path(path_str: str, allowed_roots: list[str] | None = None) -> Path:
    """Validate and resolve a path, ensuring it's within allowed roots.

    Args:
        path_str: The path string to validate
        allowed_roots: List of allowed root directories. If None, uses available drive roots.

    Returns:
        Resolved Path object

    Raises:
        HTTPException: If path is invalid or not within allowed roots
    """
    if not path_str:
        raise HTTPException(status_code=400, detail="Path cannot be empty")

    try:
        target = Path(path_str).resolve()
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")

    # Get allowed roots if not provided
    if allowed_roots is None:
        allowed_roots = list_available_roots()

    # Check if path is under any allowed root
    for root in allowed_roots:
        try:
            root_path = Path(root).resolve()
            # Check if target is the root itself or a subdirectory
            if target == root_path or root_path in target.parents:
                return target
        except (ValueError, OSError):
            continue

    raise HTTPException(
        status_code=403,
        detail=f"Access denied: path must be within allowed directories: {allowed_roots}"
    )


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
        "relative_path": track.relative_path,
        "extension": track.extension,
        "size_bytes": track.size_bytes,
        "size_display": human_size(track.size_bytes),
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "bitrate_kbps": track.bitrate_kbps,
        "duration_seconds": track.duration_seconds,
        "has_cover": track.has_cover,
        "has_lyrics": track.has_lyrics,
        "cover_hash": cover_key_for_path(track.path) if track.has_cover else "",
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
    logger.info(f"Starting scan task {task.task_id} for root: {task.root}")

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
                groups, warnings = ai_find_duplicate_groups(
                    task.tracks,
                    APP_STATE.rule_states,
                    api_url=task.ai_url,
                    api_key=task.ai_key,
                    model=task.ai_model or "gpt-4o-mini",
                    progress=progress,
                )
                APP_STATE.groups = groups
                for warning in warnings:
                    progress(f"⚠️ {warning}")
            else:
                APP_STATE.groups = find_duplicate_groups(task.tracks, APP_STATE.rule_states)
            task.groups = list(APP_STATE.groups)

        if task.stop_event.is_set():
            task.status = "stopped"
            logger.info(f"Scan task {task.task_id} stopped by user")
        else:
            task.status = "done"
        task.log.append(f"扫描完成，发现 {len(task.groups)} 组重复。")
        logger.info(f"Scan task {task.task_id} completed: {len(task.groups)} groups found")
    except Exception as exc:
        task.status = "error"
        task.error = str(exc)
        task.log.append(f"扫描出错: {exc}")
        logger.error(f"Scan task {task.task_id} failed: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Background execute worker
# ---------------------------------------------------------------------------


def _run_execute(task: ExecuteTaskState) -> None:
    """Execute deduplication in a background thread, updating task state."""
    task.status = "executing"
    task.progress_message = "准备执行去重..."
    logger.info(f"Starting execute task {task.task_id}")

    try:
        with APP_STATE.lock:
            groups = list(APP_STATE.groups)

        if not groups:
            task.status = "error"
            task.error = "no groups to process"
            task.progress_message = "没有可处理的分组"
            logger.warning(f"Execute task {task.task_id}: no groups to process")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = default_backup_dir() / timestamp
        backup.mkdir(parents=True, exist_ok=True)
        task.backup_dir = str(backup)
        logger.info(f"Execute task {task.task_id}: backup directory {backup}")

        total = sum(len(g.duplicate_tracks) for g in groups)
        task.total_count = total
        moved = 0

        for group in groups:
            for dup in group.duplicate_tracks:
                if task.stop_event.is_set():
                    task.status = "stopped"
                    task.progress_message = f"已停止，已移动 {moved}/{total} 个文件"
                    logger.info(f"Execute task {task.task_id} stopped by user")
                    return
                try:
                    if dup.path.exists():
                        shutil.move(str(dup.path), str(backup / dup.path.name))
                        moved += 1
                        task.moved_count = moved
                        task.progress_message = f"正在移动文件 ({moved}/{total})..."
                except Exception as exc:
                    task.errors.append(f"{dup.path}: {exc}")
                    logger.error(f"Execute task {task.task_id}: failed to move {dup.path}: {exc}")

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

        # Check error rate and set appropriate status
        error_count = len(task.errors)
        if total > 0 and error_count > 0:
            error_rate = error_count / total
            if error_rate >= 0.5:  # More than 50% failed
                task.status = "error"
                task.error = f"高错误率: {error_count}/{total} 个文件移动失败"
                task.progress_message = f"执行失败: {error_count}/{total} 个文件移动失败"
                logger.error(f"Execute task {task.task_id}: high error rate {error_count}/{total}")
            elif error_count > 0:
                task.status = "partial_failure"
                task.progress_message = f"部分完成: {moved} 个文件已移动，{error_count} 个失败"
                logger.warning(f"Execute task {task.task_id}: partial failure {moved} moved, {error_count} failed")
            else:
                task.progress_message = f"完成，已移动 {moved} 个文件到 {backup}"
                task.status = "done"
        else:
            task.progress_message = f"完成，已移动 {moved} 个文件到 {backup}"
            task.status = "done"

        logger.info(f"Execute task {task.task_id} completed: {moved} files moved")

    except Exception as exc:
        task.status = "error"
        task.error = str(exc)
        task.progress_message = f"执行出错: {exc}"
        logger.error(f"Execute task {task.task_id} failed: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# FastAPI application factory
# ---------------------------------------------------------------------------


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware to check Origin header for state-changing requests."""

    def __init__(self, app, allowed_origins: list[str] | None = None):
        super().__init__(app)
        self.allowed_origins = set(allowed_origins or settings.allowed_origins)

    async def dispatch(self, request: Request, call_next):
        # Only check state-changing methods
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("origin", "")
            if origin:
                # Extract origin without port
                from urllib.parse import urlparse
                parsed = urlparse(origin)
                origin_base = f"{parsed.scheme}://{parsed.hostname}"
                if origin_base not in self.allowed_origins:
                    raise HTTPException(
                        status_code=403,
                        detail="CSRF check failed: Origin not allowed"
                    )
        return await call_next(request)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="Music Deduplication", version="0.1.0")

    # Add CSRF middleware
    app.add_middleware(CSRFMiddleware)

    # Mount static files so the frontend can be served
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ---- GET /api/health ----

    @app.get("/api/health")
    def health_check() -> dict:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "version": "0.1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_scan_tasks": len([t for t in APP_STATE.tasks.values() if t.status == "scanning"]),
            "active_execute_tasks": len([t for t in APP_STATE.execute_tasks.values() if t.status == "executing"]),
        }

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
            # Validate path is within allowed roots
            target = _validate_path(path)
            if not target.exists() or not target.is_dir():
                return {"path": path, "parent": "", "children": []}
            children = sorted(
                child.name for child in target.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            )
            parent = str(target.parent) if target.parent != target else ""
            return {"path": str(target), "parent": parent, "children": children}
        except HTTPException:
            raise
        except (PermissionError, OSError):
            return {"path": path, "parent": "", "children": []}

    # ---- POST /api/scan ----

    @app.post("/api/scan")
    def start_scan(request: ScanRequest) -> dict:
        # Validate root path is within allowed directories
        try:
            _validate_path(request.root)
        except HTTPException:
            raise

        task_id = uuid.uuid4().hex[:8]
        task = ScanTaskState(
            task_id=task_id,
            root=request.root,
            algorithm=request.algorithm,
            ai_url=request.ai_url or "",
            ai_key=request.ai_key or "",
            ai_model=request.ai_model or "",
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
            raise HTTPException(status_code=404, detail="unknown task")
        with task.lock:
            return {
                "task_id": task.task_id,
                "root": task.root,
                "status": task.status,
                "progress_message": task.progress_message,
                "processed_files": task.processed_files,
                "groups_found": len(task.groups),
                "log": list(task.log),
                "error": task.error,
            }

    # ---- POST /api/scan/{task_id}/stop ----

    @app.post("/api/scan/{task_id}/stop")
    def stop_scan(task_id: str) -> dict:
        task = APP_STATE.tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="unknown task")
        task.stop_event.set()
        return {"status": "stopping"}

    # ---- PUT /api/rules ----

    @app.put("/api/rules")
    def update_rules(request: RulesUpdateRequest) -> dict:
        """Update rule states from frontend."""
        with APP_STATE.lock:
            APP_STATE.rule_states = [
                {"key": r.key, "label": r.label, "enabled": r.enabled}
                for r in request.rules
            ]
        return {"status": "ok", "rules": APP_STATE.rule_states}

    # ---- GET /api/cover/{cover_hash} ----

    @app.get("/api/cover/{cover_hash}")
    def get_cover_image(cover_hash: str):
        """Serve cached cover art image by hash key."""
        cached = get_cover(cover_hash)
        if cached is None:
            raise HTTPException(status_code=404, detail="cover not found")
        image_bytes, mime_type = cached
        return Response(content=image_bytes, media_type=mime_type)

    # ---- GET /api/tracks ----

    @app.get("/api/tracks")
    def get_tracks(
        search: str = "",
        artist: str = "",
        sort: str = "path",
        order: str = "asc",
        page: int = 1,
        page_size: int = 200,
    ) -> dict:
        """Return all scanned tracks with search/filter/sort/pagination."""
        with APP_STATE.lock:
            all_tracks = list(APP_STATE.tracks)

        filtered = all_tracks
        if search:
            s = search.lower()
            filtered = [
                t for t in filtered
                if s in (t.title or "").lower()
                or s in (t.artist or "").lower()
                or s in (t.album or "").lower()
                or s in (t.relative_path or "").lower()
            ]

        if artist:
            a = artist.lower()
            filtered = [t for t in filtered if a in (t.artist or "").lower()]

        reverse = order == "desc"
        sort_key_map = {
            "title": lambda t: (t.title or "").lower(),
            "artist": lambda t: (t.artist or "").lower(),
            "album": lambda t: (t.album or "").lower(),
            "size": lambda t: t.size_bytes,
            "bitrate": lambda t: t.bitrate_kbps or 0,
            "duration": lambda t: t.duration_seconds or 0,
            "format": lambda t: t.extension.lower(),
        }
        key_fn = sort_key_map.get(sort, lambda t: (t.relative_path or "").lower())
        filtered.sort(key=key_fn, reverse=reverse)

        total = len(filtered)
        start = (page - 1) * page_size
        page_tracks = filtered[start:start + page_size]

        total_size = sum(t.size_bytes for t in all_tracks)
        formats: dict[str, int] = {}
        for t in all_tracks:
            fmt = t.extension.upper().lstrip(".")
            formats[fmt] = formats.get(fmt, 0) + 1
        avg_bitrate = (
            sum(t.bitrate_kbps or 0 for t in all_tracks) // len(all_tracks)
            if all_tracks else 0
        )

        return {
            "tracks": [_track_to_dict(t) for t in page_tracks],
            "total": total,
            "page": page,
            "page_size": page_size,
            "stats": {
                "total_tracks": len(all_tracks),
                "total_size": total_size,
                "total_size_display": human_size(total_size),
                "formats": formats,
                "avg_bitrate": avg_bitrate,
            },
        }

    # ---- PUT /api/tracks/update ----

    class TrackUpdateRequest(BaseModel):
        path: str
        title: str | None = None
        artist: str | None = None
        album: str | None = None
        year: int | None = None
        genre: str | None = None
        track_number: int | None = None

    @app.put("/api/tracks/update")
    def update_track_metadata(request: TrackUpdateRequest) -> dict:
        """Update metadata tags on an audio file."""
        target = Path(request.path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="file not found")

        try:
            from mutagen import File as MutagenFile
            from mutagen.id3 import TIT2, TPE1, TALB, TDRC, TCON, TRCK

            ext = target.suffix.lower()
            mf = MutagenFile(target)
            if mf is None:
                raise HTTPException(status_code=400, detail="unsupported format")

            if ext == ".mp3":
                if mf.tags is None:
                    mf.add_tags()
                tags = mf.tags
                if request.title is not None:
                    tags.add(TIT2(encoding=3, text=[request.title]))
                if request.artist is not None:
                    tags.add(TPE1(encoding=3, text=[request.artist]))
                if request.album is not None:
                    tags.add(TALB(encoding=3, text=[request.album]))
                if request.year is not None:
                    tags.add(TDRC(encoding=3, text=[str(request.year)]))
                if request.genre is not None:
                    tags.add(TCON(encoding=3, text=[request.genre]))
                if request.track_number is not None:
                    tags.add(TRCK(encoding=3, text=[str(request.track_number)]))
                mf.save()
            elif ext in {".m4a", ".mp4", ".aac", ".alac"}:
                if mf.tags is None:
                    mf.add_tags()
                tags = mf.tags
                if request.title is not None:
                    tags["\xa9nam"] = [request.title]
                if request.artist is not None:
                    tags["\xa9ART"] = [request.artist]
                if request.album is not None:
                    tags["\xa9alb"] = [request.album]
                if request.year is not None:
                    tags["\xa9day"] = [str(request.year)]
                if request.genre is not None:
                    tags["\xa9gen"] = [request.genre]
                if request.track_number is not None:
                    tags["trkn"] = [(request.track_number, 0)]
                mf.save()
            elif ext == ".wma":
                if mf.tags is None:
                    mf.add_tags()
                tags = mf.tags
                if request.title is not None:
                    tags["Title"] = [request.title]
                if request.artist is not None:
                    tags["Author"] = [request.artist]
                if request.album is not None:
                    tags["WM/AlbumTitle"] = [request.album]
                if request.year is not None:
                    tags["WM/Year"] = [str(request.year)]
                if request.genre is not None:
                    tags["WM/Genre"] = [request.genre]
                if request.track_number is not None:
                    tags["WM/TrackNumber"] = [str(request.track_number)]
                mf.save()
            elif ext in {".flac", ".ogg"}:
                if mf.tags is None:
                    mf.add_tags()
                tags = mf.tags
                if request.title is not None:
                    tags["title"] = [request.title]
                if request.artist is not None:
                    tags["artist"] = [request.artist]
                if request.album is not None:
                    tags["album"] = [request.album]
                if request.year is not None:
                    tags["date"] = [str(request.year)]
                if request.genre is not None:
                    tags["genre"] = [request.genre]
                if request.track_number is not None:
                    tags["tracknumber"] = [str(request.track_number)]
                mf.save()
            else:
                raise HTTPException(status_code=400, detail=f"tag writing not supported for {ext}")

            # Update in-memory state
            with APP_STATE.lock:
                from dataclasses import replace as dc_replace
                for idx, t in enumerate(APP_STATE.tracks):
                    if str(t.path) == request.path:
                        updates = {}
                        for field_name in ("title", "artist", "album", "year", "genre", "track_number"):
                            val = getattr(request, field_name, None)
                            if val is not None:
                                updates[field_name] = val
                        APP_STATE.tracks[idx] = dc_replace(t, **updates)
                        break

            logger.info(f"Updated metadata for {target}")
            return {"status": "ok"}

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to update metadata for {target}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

    # ---- PUT /api/tracks/batch-update ----

    @app.put("/api/tracks/batch-update")
    def batch_update_tracks(batch_req: BatchUpdateRequest) -> dict:
        """Update metadata tags on multiple audio files at once."""
        if not batch_req.paths:
            raise HTTPException(status_code=400, detail="no paths provided")

        updated = 0
        errors: list[str] = []
        allowed_fields = {"title", "artist", "album", "year", "genre", "track_number"}

        for path_str in batch_req.paths:
            target = Path(path_str)
            if not target.exists():
                errors.append(f"{path_str}: file not found")
                continue

            try:
                from mutagen import File as MutagenFile
                from mutagen.id3 import TIT2, TPE1, TALB, TDRC, TCON, TRCK

                ext = target.suffix.lower()
                mf = MutagenFile(target)
                if mf is None:
                    errors.append(f"{path_str}: unsupported format")
                    continue

                # Build per-field updates
                field_updates = {k: v for k, v in batch_req.updates.items() if k in allowed_fields}

                if ext == ".mp3":
                    if mf.tags is None:
                        mf.add_tags()
                    tag_map = {"title": TIT2, "artist": TPE1, "album": TALB, "year": TDRC, "genre": TCON, "track_number": TRCK}
                    for field, cls in tag_map.items():
                        if field in field_updates:
                            val = field_updates[field]
                            if val is not None:
                                mf.tags.add(cls(encoding=3, text=[str(val)]))
                    mf.save()
                elif ext in {".m4a", ".mp4", ".aac", ".alac"}:
                    if mf.tags is None:
                        mf.add_tags()
                    key_map = {"title": "©nam", "artist": "©ART", "album": "©alb", "year": "©day", "genre": "©gen"}
                    for field, tag_key in key_map.items():
                        if field in field_updates:
                            val = field_updates[field]
                            if val is not None:
                                mf.tags[tag_key] = [str(val)]
                    if "track_number" in field_updates and field_updates["track_number"] is not None:
                        mf.tags["trkn"] = [(int(field_updates["track_number"]), 0)]
                    mf.save()
                elif ext == ".wma":
                    if mf.tags is None:
                        mf.add_tags()
                    key_map = {"title": "Title", "artist": "Author", "album": "WM/AlbumTitle", "year": "WM/Year", "genre": "WM/Genre", "track_number": "WM/TrackNumber"}
                    for field, tag_key in key_map.items():
                        if field in field_updates:
                            val = field_updates[field]
                            if val is not None:
                                mf.tags[tag_key] = [str(val)]
                    mf.save()
                elif ext in {".flac", ".ogg"}:
                    if mf.tags is None:
                        mf.add_tags()
                    key_map = {"title": "title", "artist": "artist", "album": "album", "year": "date", "genre": "genre", "track_number": "tracknumber"}
                    for field, tag_key in key_map.items():
                        if field in field_updates:
                            val = field_updates[field]
                            if val is not None:
                                mf.tags[tag_key] = [str(val)]
                    mf.save()
                else:
                    errors.append(f"{path_str}: unsupported format {ext}")
                    continue

                # Update in-memory state
                with APP_STATE.lock:
                    from dataclasses import replace as dc_replace
                    for idx, t in enumerate(APP_STATE.tracks):
                        if str(t.path) == path_str:
                            mem_updates = {k: (int(v) if k in ("year", "track_number") and v else v) for k, v in field_updates.items() if v is not None}
                            APP_STATE.tracks[idx] = dc_replace(t, **mem_updates)
                            break

                updated += 1
            except Exception as exc:
                errors.append(f"{path_str}: {exc}")

        logger.info(f"Batch update: {updated}/{len(batch_req.paths)} files updated")
        return {"updated": updated, "total": len(batch_req.paths), "errors": errors}

    # ---- GET /api/tracks/lyrics ----

    @app.get("/api/tracks/lyrics")
    def get_track_lyrics(path: str) -> dict:
        """Extract and return embedded lyrics text from an audio file."""
        target = Path(path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="file not found")

        try:
            from mutagen import File as MutagenFile
            from .audio_metadata import (
                _extract_id3_lyrics_text, _extract_mp4_lyrics_text,
                _extract_wma_lyrics_text, _extract_vorbis_lyrics_text,
            )

            ext = target.suffix.lower()
            mf = MutagenFile(target)
            if mf is None:
                return {"lyrics": "", "has_lyrics": False}

            tags = mf.tags or {}
            lyrics = ""

            if ext in {".mp3", ".dsf"}:
                lyrics = _extract_id3_lyrics_text(tags)
            elif ext in {".m4a", ".mp4", ".aac", ".alac"}:
                lyrics = _extract_mp4_lyrics_text(tags)
            elif ext == ".wma":
                lyrics = _extract_wma_lyrics_text(tags)
            elif ext in {".flac", ".ogg"}:
                lyrics = _extract_vorbis_lyrics_text(tags)

            return {"lyrics": lyrics, "has_lyrics": bool(lyrics.strip())}

        except Exception as exc:
            logger.error(f"Failed to read lyrics for {target}: {exc}")
            return {"lyrics": "", "has_lyrics": False}

    # ---- PUT /api/tracks/lyrics ----

    class LyricsUpdateRequest(BaseModel):
        path: str
        lyrics: str

    @app.put("/api/tracks/lyrics")
    def update_track_lyrics(req: LyricsUpdateRequest) -> dict:
        """Write lyrics text into an audio file's tags."""
        target = Path(req.path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="file not found")

        try:
            from mutagen import File as MutagenFile
            from mutagen.id3 import USLT

            ext = target.suffix.lower()
            mf = MutagenFile(target)
            if mf is None:
                raise HTTPException(status_code=400, detail="unsupported format")

            lyrics_text = req.lyrics.strip()

            if ext in {".mp3", ".dsf"}:
                if mf.tags is None:
                    mf.add_tags()
                if lyrics_text:
                    mf.tags.add(USLT(encoding=3, lang="eng", desc="", text=[lyrics_text]))
                else:
                    # Remove lyrics if empty
                    try:
                        mf.tags.delall("USLT")
                    except Exception:
                        pass
                mf.save()
            elif ext in {".m4a", ".mp4", ".aac", ".alac"}:
                if mf.tags is None:
                    mf.add_tags()
                if lyrics_text:
                    mf.tags["©lyr"] = [lyrics_text]
                else:
                    mf.tags.pop("©lyr", None)
                mf.save()
            elif ext == ".wma":
                if mf.tags is None:
                    mf.add_tags()
                if lyrics_text:
                    mf.tags["WM/Lyrics"] = [lyrics_text]
                else:
                    mf.tags.pop("WM/Lyrics", None)
                mf.save()
            elif ext in {".flac", ".ogg"}:
                if mf.tags is None:
                    mf.add_tags()
                if lyrics_text:
                    mf.tags["LYRICS"] = [lyrics_text]
                else:
                    mf.tags.pop("LYRICS", None)
                    mf.tags.pop("UNSYNCEDLYRICS", None)
                mf.save()
            else:
                raise HTTPException(status_code=400, detail=f"lyrics writing not supported for {ext}")

            # Update in-memory state
            with APP_STATE.lock:
                from dataclasses import replace as dc_replace
                for idx, t in enumerate(APP_STATE.tracks):
                    if str(t.path) == req.path:
                        APP_STATE.tracks[idx] = dc_replace(t, has_lyrics=bool(lyrics_text))
                        break

            logger.info(f"Updated lyrics for {target}")
            return {"status": "ok"}

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to write lyrics for {target}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

    # ---- POST /api/tracks/cover ----

    @app.post("/api/tracks/cover")
    async def update_track_cover(
        path: str = Form(...),
        cover: UploadFile = FastAPIFile(...),
    ) -> dict:
        """Upload and embed a new cover image into an audio file."""
        target = Path(path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="file not found")

        try:
            image_bytes = await cover.read()
            mime_type = cover.content_type or "image/jpeg"

            from mutagen import File as MutagenFile
            from mutagen.id3 import APIC

            ext = target.suffix.lower()
            mf = MutagenFile(target)
            if mf is None:
                raise HTTPException(status_code=400, detail="unsupported format")

            if ext in {".mp3", ".dsf"}:
                if mf.tags is None:
                    mf.add_tags()
                mf.tags.add(APIC(encoding=3, mime=mime_type, type=3, desc="Cover", data=image_bytes))
                mf.save()
            elif ext in {".m4a", ".mp4", ".aac", ".alac"}:
                if mf.tags is None:
                    mf.add_tags()
                from mutagen.mp4 import MP4Cover
                fmt = 0x0E if "png" in mime_type else 0x0D
                mf.tags["covr"] = [MP4Cover(image_bytes, imageformat=fmt)]
                mf.save()
            elif ext in {".flac", ".ogg"}:
                import struct as _struct
                mime_bytes = mime_type.encode("ascii")
                desc_bytes = b"Cover"
                pic_data = _struct.pack(">I", 3)
                pic_data += _struct.pack(">I", len(mime_bytes)) + mime_bytes
                pic_data += _struct.pack(">I", len(desc_bytes)) + desc_bytes
                pic_data += _struct.pack(">II", 0, 0)
                pic_data += _struct.pack(">II", 0, 0)
                pic_data += _struct.pack(">I", len(image_bytes)) + image_bytes
                encoded = base64.b64encode(pic_data).decode("ascii")
                if mf.tags is None:
                    mf.add_tags()
                mf.tags["metadata_block_picture"] = [encoded]
                mf.save()
            elif ext == ".wma":
                from mutagen.asf import ASFByteArrayAttribute
                if mf.tags is None:
                    mf.add_tags()
                mf.tags["WM/Picture"] = [ASFByteArrayAttribute(image_bytes)]
                mf.save()
            else:
                raise HTTPException(status_code=400, detail=f"cover writing not supported for {ext}")

            from .audio_metadata import cache_cover
            cache_cover(target, image_bytes, mime_type)
            with APP_STATE.lock:
                from dataclasses import replace as dc_replace
                for idx, t in enumerate(APP_STATE.tracks):
                    if str(t.path) == path:
                        APP_STATE.tracks[idx] = dc_replace(t, has_cover=True)
                        break

            logger.info(f"Updated cover for {target}")
            return {"status": "ok"}

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to update cover for {target}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

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
        raise HTTPException(status_code=404, detail="group not found")

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
                        raise HTTPException(status_code=404, detail="track not found in group")

                    # Replace keep_track and rebuild duplicate list
                    APP_STATE.groups[i] = DuplicateGroup(
                        key=g.key,
                        tracks=g.tracks,
                        keep_track=target,
                        duplicate_tracks=[t for t in g.tracks if t.path != target.path],
                    )
                    return _group_to_dict(i, APP_STATE.groups[i])
        raise HTTPException(status_code=404, detail="group not found")

    # ---- POST /api/execute ----

    @app.post("/api/execute")
    def execute_dedupe() -> dict:
        with APP_STATE.lock:
            groups = list(APP_STATE.groups)

        if not groups:
            raise HTTPException(status_code=400, detail="no groups to process")

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
            raise HTTPException(status_code=404, detail="unknown task")
        with task.lock:
            return {
                "task_id": task.task_id,
                "status": task.status,
                "progress_message": task.progress_message,
                "moved_count": task.moved_count,
                "total_count": task.total_count,
                "backup_dir": task.backup_dir,
                "errors": list(task.errors),
            }

    # ---- POST /api/execute/{task_id}/stop ----

    @app.post("/api/execute/{task_id}/stop")
    def stop_execute(task_id: str) -> dict:
        task = APP_STATE.execute_tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="unknown task")
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
