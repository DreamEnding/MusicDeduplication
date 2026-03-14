from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import ctypes
import os
import threading

from .audio_metadata import SUPPORTED_EXTENSIONS, read_audio_track
from .models import AudioTrack

ProgressCallback = Callable[[str], None]


def list_available_roots() -> list[str]:
    if os.name == "nt":
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = []
        for index in range(26):
            if bitmask & (1 << index):
                drives.append(f"{chr(65 + index)}:\\")
        return drives
    return [str(Path("/"))]


def scan_audio_files(root: Path, progress: ProgressCallback | None = None, stop_event: threading.Event | None = None) -> list[AudioTrack]:
    progress = progress or (lambda _message: None)
    stop_event = stop_event or threading.Event()
    tracks: list[AudioTrack] = []
    processed = 0

    progress(f"开始扫描 {root}")
    for current_root, dirnames, filenames in os.walk(root):
        if stop_event.is_set():
            progress("扫描被手动停止。")
            break
        dirnames.sort()
        filenames.sort()
        for filename in filenames:
            file_path = Path(current_root) / filename
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            processed += 1
            track = read_audio_track(file_path, root)
            tracks.append(track)
            if processed % 25 == 0:
                progress(f"已分析 {processed} 首音频: {track.relative_path}")
    progress(f"扫描结束，共识别到 {len(tracks)} 首音频文件。")
    return tracks
