# HTML Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the tkinter desktop music deduplication tool to a local web application with FastAPI backend and vanilla HTML/CSS/JS frontend.

**Architecture:** FastAPI serves both REST API endpoints and static files from a single process. The scanner runs in background threads with status polling. The frontend uses vanilla JS with no build step, communicating with the backend via JSON API calls. Audio metadata parsing is migrated from hand-written binary parsers to the mutagen library for broader format coverage.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, mutagen, vanilla HTML/CSS/JS (no framework)

---

## Task 1: Update pyproject.toml

**File:** `D:/MusicDeduplication/pyproject.toml`

**Goal:** Add FastAPI, Uvicorn, and mutagen dependencies so the project installs with the web stack and metadata parser.

**TDD:** Not applicable for dependency declaration. Verification is installation plus import checks.

### Steps

- [ ] **1.1** Overwrite `D:/MusicDeduplication/pyproject.toml` with the exact content below:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "music-deduplication"
version = "0.1.0"
description = "桌面端音乐去重工具，支持按元信息、码率、封面等规则保留最佳文件。"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "mutagen>=1.47",
]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **1.2** Install the package in editable mode and verify the new dependencies import correctly:

```powershell
Set-Location D:/MusicDeduplication
pip install -e .
python -c "import fastapi, uvicorn, mutagen; print('dependency import check passed')"
```

---

## Task 2: Extend AudioTrack model

**File:** `D:/MusicDeduplication/src/music_deduper/models.py`

**Goal:** Add `year`, `genre`, `track_number`, and `format_info` to `AudioTrack` without breaking existing rule behavior.

**TDD:** Write the model tests first, run them red, then update the dataclass and rerun green.

### Steps

- [ ] **2.1** Create `D:/MusicDeduplication/tests/test_models.py` with the exact test suite below:

```python
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from music_deduper.models import AudioTrack, DuplicateGroup


def test_audio_track_defaults_include_new_fields() -> None:
    track = AudioTrack(
        path=Path("D:/music/example.mp3"),
        root=Path("D:/music"),
        extension=".mp3",
        size_bytes=1234,
    )
    assert track.year is None
    assert track.genre == ""
    assert track.track_number is None
    assert track.format_info == ""


def test_audio_track_accepts_new_fields() -> None:
    track = AudioTrack(
        path=Path("D:/music/example.mp3"),
        root=Path("D:/music"),
        extension=".mp3",
        size_bytes=1234,
        title="Example",
        artist="Artist",
        album="Album",
        year=2024,
        genre="Pop",
        track_number=7,
        format_info="MP3 320 kbps",
    )
    assert track.title == "Example"
    assert track.artist == "Artist"
    assert track.album == "Album"
    assert track.year == 2024
    assert track.genre == "Pop"
    assert track.track_number == 7
    assert track.format_info == "MP3 320 kbps"


def test_existing_computed_properties_still_work() -> None:
    track = AudioTrack(
        path=Path("D:/music/folder/track.mp3"),
        root=Path("D:/music"),
        extension=".mp3",
        size_bytes=2048,
        title="Song",
        artist="Singer",
        album="Album",
    )
    assert track.relative_path == "folder\\track.mp3" or track.relative_path == "folder/track.mp3"
    assert track.filename_stem == "track"
    assert track.metadata_filled_count == 3
    assert track.has_core_metadata is True
    assert track.display_title == "Song"
    assert track.display_artist == "Singer"
    assert track.display_album == "Album"
    assert track.path_depth == 2


def test_duplicate_group_reclaimable_bytes_unchanged() -> None:
    keep = AudioTrack(
        path=Path("D:/music/keep.mp3"),
        root=Path("D:/music"),
        extension=".mp3",
        size_bytes=5000,
    )
    duplicate = AudioTrack(
        path=Path("D:/music/dup.mp3"),
        root=Path("D:/music"),
        extension=".mp3",
        size_bytes=3000,
    )
    group = DuplicateGroup(
        key="example",
        tracks=[keep, duplicate],
        keep_track=keep,
        duplicate_tracks=[duplicate],
    )
    assert group.reclaimable_bytes == 3000
```

- [ ] **2.2** Run the new model test first and confirm the dataclass is still missing the new fields:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_models.py -v
```

- [ ] **2.3** Overwrite `D:/MusicDeduplication/src/music_deduper/models.py` with the exact implementation below:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class AudioTrack:
    path: Path
    root: Path
    extension: str
    size_bytes: int
    title: str = ""
    artist: str = ""
    album: str = ""
    bitrate_kbps: int | None = None
    duration_seconds: float | None = None
    has_cover: bool = False
    metadata_source: str = ""
    year: int | None = None
    genre: str = ""
    track_number: int | None = None
    format_info: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def relative_path(self) -> str:
        try:
            return str(self.path.relative_to(self.root))
        except ValueError:
            return str(self.path)

    @property
    def filename_stem(self) -> str:
        return self.path.stem

    @property
    def metadata_filled_count(self) -> int:
        return sum(1 for item in (self.title, self.artist, self.album) if item.strip())

    @property
    def has_core_metadata(self) -> bool:
        return bool(self.title.strip() and self.artist.strip())

    @property
    def display_title(self) -> str:
        return self.title.strip() or self.filename_stem

    @property
    def display_artist(self) -> str:
        return self.artist.strip() or "未知歌手"

    @property
    def display_album(self) -> str:
        return self.album.strip() or "未知专辑"

    @property
    def path_depth(self) -> int:
        return len(Path(self.relative_path).parts)


@dataclass(slots=True)
class DuplicateGroup:
    key: str
    tracks: list[AudioTrack]
    keep_track: AudioTrack
    duplicate_tracks: list[AudioTrack]

    @property
    def reclaimable_bytes(self) -> int:
        return sum(track.size_bytes for track in self.duplicate_tracks)


@dataclass(slots=True)
class RuleState:
    key: str
    label: str
    description: str
    enabled: bool = True
```

- [ ] **2.4** Run the focused model tests and the existing rule tests to confirm backward compatibility:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_models.py tests/test_rules.py -v
```

---

## Task 3: Rewrite audio_metadata.py with mutagen

**File:** `D:/MusicDeduplication/src/music_deduper/audio_metadata.py`

**Goal:** Replace the hand-written MP3 and FLAC readers with a single mutagen-based metadata reader while keeping `read_audio_track(path, root) -> AudioTrack` unchanged.

**TDD:** Add mutagen-focused tests first, then replace the implementation.

### Steps

- [ ] **3.1** Create `D:/MusicDeduplication/tests/test_audio_metadata.py` with the exact tests below:

```python
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import music_deduper.audio_metadata as audio_metadata


class FakeAudio:
    def __init__(self, tags: dict[str, object], info: object) -> None:
        self.tags = tags
        self.info = info


def test_read_audio_track_mp3_uses_mutagen_tags(tmp_path, monkeypatch) -> None:
    path = tmp_path / "track.mp3"
    path.write_bytes(b"mp3")

    fake_audio = FakeAudio(
        tags={
            "TIT2": ["Blue Train"],
            "TPE1": ["John Coltrane"],
            "TALB": ["Blue Train"],
            "TDRC": ["1957"],
            "TCON": ["Jazz"],
            "TRCK": ["2/5"],
            "APIC:cover": b"cover-bytes",
        },
        info=SimpleNamespace(length=600.2, bitrate=320_000, bitrate_mode="CBR"),
    )

    monkeypatch.setattr(audio_metadata, "MutagenFile", lambda *_args, **_kwargs: fake_audio)

    track = audio_metadata.read_audio_track(path, tmp_path)

    assert track.title == "Blue Train"
    assert track.artist == "John Coltrane"
    assert track.album == "Blue Train"
    assert track.bitrate_kbps == 320
    assert track.duration_seconds == 600.2
    assert track.has_cover is True
    assert track.year == 1957
    assert track.genre == "Jazz"
    assert track.track_number == 2
    assert track.format_info == "MP3 CBR 320 kbps"
    assert track.metadata_source == "FakeAudio"


def test_read_audio_track_mp4_handles_copyright_prefix_keys(tmp_path, monkeypatch) -> None:
    path = tmp_path / "track.m4a"
    path.write_bytes(b"m4a")

    fake_audio = FakeAudio(
        tags={
            "\xa9nam": ["Track Name"],
            "\xa9ART": ["Artist Name"],
            "\xa9alb": ["Album Name"],
            "\xa9day": ["2021-11-01"],
            "\xa9gen": ["Synthpop"],
            "trkn": [(9, 12)],
            "covr": [b"cover"],
        },
        info=SimpleNamespace(length=245.0, bitrate=256_000, codec="AAC LC"),
    )

    monkeypatch.setattr(audio_metadata, "MutagenFile", lambda *_args, **_kwargs: fake_audio)

    track = audio_metadata.read_audio_track(path, tmp_path)

    assert track.title == "Track Name"
    assert track.artist == "Artist Name"
    assert track.album == "Album Name"
    assert track.year == 2021
    assert track.genre == "Synthpop"
    assert track.track_number == 9
    assert track.has_cover is True
    assert track.format_info == "AAC LC 256 kbps"


def test_read_audio_track_wma_handles_wm_prefix_tags(tmp_path, monkeypatch) -> None:
    path = tmp_path / "track.wma"
    path.write_bytes(b"wma")

    fake_audio = FakeAudio(
        tags={
            "Title": ["WMA Song"],
            "Author": ["WMA Artist"],
            "WM/AlbumTitle": ["WMA Album"],
            "WM/Year": ["2003"],
            "WM/Genre": ["Rock"],
            "WM/TrackNumber": ["11"],
            "WM/Picture": [b"cover"],
        },
        info=SimpleNamespace(length=301.0, bitrate=192_000),
    )

    monkeypatch.setattr(audio_metadata, "MutagenFile", lambda *_args, **_kwargs: fake_audio)

    track = audio_metadata.read_audio_track(path, tmp_path)

    assert track.title == "WMA Song"
    assert track.artist == "WMA Artist"
    assert track.album == "WMA Album"
    assert track.year == 2003
    assert track.genre == "Rock"
    assert track.track_number == 11
    assert track.has_cover is True
    assert track.format_info == "WMA 192 kbps"


def test_read_audio_track_handles_mutagen_failure(tmp_path, monkeypatch) -> None:
    path = tmp_path / "broken.flac"
    path.write_bytes(b"broken")

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(audio_metadata, "MutagenFile", explode)

    track = audio_metadata.read_audio_track(path, tmp_path)

    assert track.title == ""
    assert track.artist == ""
    assert track.album == ""
    assert track.warnings == ["解析失败: boom"]
```

- [ ] **3.2** Run the metadata tests and confirm they fail against the old handwritten parser:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_audio_metadata.py -v
```

- [ ] **3.3** Overwrite `D:/MusicDeduplication/src/music_deduper/audio_metadata.py` with the exact mutagen-based implementation below:

```python
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

from mutagen import File as MutagenFile

from .models import AudioTrack

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".wma"}


def read_audio_track(path: Path, root: Path) -> AudioTrack:
    base = AudioTrack(
        path=path,
        root=root,
        extension=path.suffix.lower(),
        size_bytes=path.stat().st_size,
    )

    try:
        audio = MutagenFile(path)
        if audio is None:
            base.warnings.append("解析失败: mutagen 无法识别该文件")
            return base

        info = getattr(audio, "info", None)
        tags = _normalize_tags(getattr(audio, "tags", None))

        title = _pick_text(tags, _title_keys(base.extension))
        artist = _pick_text(tags, _artist_keys(base.extension))
        album = _pick_text(tags, _album_keys(base.extension))
        year = _parse_year(_pick_text(tags, _year_keys(base.extension)))
        genre = _pick_text(tags, _genre_keys(base.extension))
        track_number = _parse_track_number(tags, base.extension)
        has_cover = _has_cover(tags, base.extension)
        bitrate_kbps = _extract_bitrate_kbps(info)
        duration_seconds = _extract_duration_seconds(info)
        format_info = _build_format_info(base.extension, info, bitrate_kbps)
        metadata_source = type(audio).__name__

        return replace(
            base,
            title=title,
            artist=artist,
            album=album,
            bitrate_kbps=bitrate_kbps,
            duration_seconds=duration_seconds,
            has_cover=has_cover,
            metadata_source=metadata_source,
            year=year,
            genre=genre,
            track_number=track_number,
            format_info=format_info,
        )
    except Exception as exc:  # pragma: no cover
        base.warnings.append(f"解析失败: {exc}")
        return base


def _normalize_tags(tags: object) -> dict[str, list[object]]:
    if not tags:
        return {}

    normalized: dict[str, list[object]] = {}
    for key, value in dict(tags).items():
        if isinstance(value, list):
            normalized[str(key)] = value
        else:
            normalized[str(key)] = [value]
    return normalized


def _pick_text(tags: dict[str, list[object]], keys: list[str]) -> str:
    for key in keys:
        values = tags.get(key)
        if not values:
            continue
        value = values[0]
        if isinstance(value, tuple):
            value = value[0]
        text = str(value).strip()
        if text:
            return text
    return ""


def _title_keys(extension: str) -> list[str]:
    if extension in {".m4a", ".aac"}:
        return ["\xa9nam", "title"]
    if extension == ".wma":
        return ["Title", "WM/Title", "title"]
    return ["TIT2", "title"]


def _artist_keys(extension: str) -> list[str]:
    if extension in {".m4a", ".aac"}:
        return ["\xa9ART", "aART", "artist"]
    if extension == ".wma":
        return ["Author", "WM/AlbumArtist", "artist"]
    return ["TPE1", "artist"]


def _album_keys(extension: str) -> list[str]:
    if extension in {".m4a", ".aac"}:
        return ["\xa9alb", "album"]
    if extension == ".wma":
        return ["WM/AlbumTitle", "album"]
    return ["TALB", "album"]


def _year_keys(extension: str) -> list[str]:
    if extension in {".m4a", ".aac"}:
        return ["\xa9day", "date", "year"]
    if extension == ".wma":
        return ["WM/Year", "year", "date"]
    return ["TDRC", "TYER", "date", "year"]


def _genre_keys(extension: str) -> list[str]:
    if extension in {".m4a", ".aac"}:
        return ["\xa9gen", "genre"]
    if extension == ".wma":
        return ["WM/Genre", "genre"]
    return ["TCON", "genre"]


def _track_keys(extension: str) -> list[str]:
    if extension in {".m4a", ".aac"}:
        return ["trkn", "tracknumber"]
    if extension == ".wma":
        return ["WM/TrackNumber", "tracknumber"]
    return ["TRCK", "tracknumber"]


def _cover_keys(extension: str) -> list[str]:
    if extension in {".m4a", ".aac"}:
        return ["covr"]
    if extension == ".wma":
        return ["WM/Picture"]
    return ["APIC", "metadata_block_picture", "covr"]


def _parse_year(value: str) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", value)
    if not match:
        return None
    return int(match.group(0))


def _parse_track_number(tags: dict[str, list[object]], extension: str) -> int | None:
    for key in _track_keys(extension):
        values = tags.get(key)
        if not values:
            continue
        value = values[0]
        if isinstance(value, tuple) and value:
            number = value[0]
            if isinstance(number, int):
                return number
            if str(number).isdigit():
                return int(str(number))
        text = str(value).strip()
        match = re.match(r"(\d+)", text)
        if match:
            return int(match.group(1))
    return None


def _has_cover(tags: dict[str, list[object]], extension: str) -> bool:
    for key in _cover_keys(extension):
        if key in tags and tags[key]:
            return True

    for key, values in tags.items():
        lowered = key.lower()
        if lowered.startswith("apic") and values:
            return True
        if lowered == "metadata_block_picture" and values:
            return True
    return False


def _extract_bitrate_kbps(info: object) -> int | None:
    if info is None:
        return None
    bitrate = getattr(info, "bitrate", None)
    if bitrate is None:
        return None
    return int(round(float(bitrate) / 1000))


def _extract_duration_seconds(info: object) -> float | None:
    if info is None:
        return None
    length = getattr(info, "length", None)
    if length is None:
        return None
    return round(float(length), 3)


def _build_format_info(extension: str, info: object, bitrate_kbps: int | None) -> str:
    ext_map = {
        ".mp3": "MP3",
        ".flac": "FLAC",
        ".wav": "WAV",
        ".aac": "AAC",
        ".m4a": "AAC LC",
        ".ogg": "OGG",
        ".wma": "WMA",
    }
    label = ext_map.get(extension, extension.lstrip(".").upper())

    codec = getattr(info, "codec", None)
    if codec:
        label = str(codec)

    bitrate_mode = getattr(info, "bitrate_mode", None)
    if bitrate_mode and extension == ".mp3":
        label = f"{label} {str(bitrate_mode).upper()}"

    if bitrate_kbps is not None:
        return f"{label} {bitrate_kbps} kbps"
    return label
```

- [ ] **3.4** Run the metadata test suite again:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_audio_metadata.py -v
```

---

## Task 4: Update existing tests and add mutagen-adjacent scanner tests

**File:** `D:/MusicDeduplication/tests/test_rules.py` and `D:/MusicDeduplication/tests/test_scanner.py`

**Goal:** Keep the current dedupe rule coverage intact and add scanner coverage for root listing and recursive audio discovery.

**TDD:** The new scanner tests should fail until the scanner integration is wired against the updated metadata module.

### Steps

- [ ] **4.1** Overwrite `D:/MusicDeduplication/tests/test_rules.py` with the verified version below:

```python
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from music_deduper.dedupe import (
    build_dedupe_key,
    build_dedupe_signatures,
    default_rule_states,
    find_duplicate_groups,
    normalize_text,
    select_preferred_track,
)
from music_deduper.models import AudioTrack


class RuleTests(unittest.TestCase):
    def test_normalize_text(self) -> None:
        self.assertEqual(normalize_text("Hello - World (Live)"), "hello world")

    def test_build_key_prefers_title_artist(self) -> None:
        track = AudioTrack(
            path=Path("A:/Song.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=1024,
            title="Blue Train",
            artist="John Coltrane",
            year=1957,
            genre="Jazz",
        )
        self.assertTrue(build_dedupe_key(track).startswith("pair::"))

    def test_select_preferred_track(self) -> None:
        rules = default_rule_states()
        low = AudioTrack(
            path=Path("A:/low.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=1_000_000,
            title="Song",
            artist="Singer",
            album="Album",
            bitrate_kbps=128,
            has_cover=False,
            year=2020,
            genre="Pop",
            track_number=1,
            format_info="MP3 128 kbps",
        )
        high = AudioTrack(
            path=Path("A:/high.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=2_000_000,
            title="Song",
            artist="Singer",
            album="Album",
            bitrate_kbps=320,
            has_cover=True,
            year=2020,
            genre="Pop",
            track_number=1,
            format_info="MP3 320 kbps",
        )
        preferred = select_preferred_track([low, high], rules)
        self.assertEqual(preferred.path.name, "high.mp3")

    def test_reverse_filename_pair_creates_shared_pair_signature(self) -> None:
        left = AudioTrack(
            path=Path("A:/周杰伦-菊花台.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=100,
        )
        right = AudioTrack(
            path=Path("A:/菊花台-周杰伦.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=120,
        )
        shared = build_dedupe_signatures(left) & build_dedupe_signatures(right)
        self.assertIn("pair::周杰伦::菊花台", shared)

    def test_find_duplicate_groups_matches_filename_reversal(self) -> None:
        rules = default_rule_states()
        metadata_track = AudioTrack(
            path=Path("A:/album/菊花台.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=2_000_000,
            title="菊花台",
            artist="周杰伦",
            album="依然范特西",
            bitrate_kbps=320,
            has_cover=True,
            year=2006,
            genre="Mandopop",
            track_number=4,
            format_info="MP3 320 kbps",
        )
        filename_track = AudioTrack(
            path=Path("A:/mix/周杰伦-菊花台.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=1_000_000,
            bitrate_kbps=128,
            format_info="MP3 128 kbps",
        )
        groups = find_duplicate_groups([metadata_track, filename_track], rules)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].keep_track.path, metadata_track.path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **4.2** Create `D:/MusicDeduplication/tests/test_scanner.py` with the exact scanner coverage below:

```python
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from music_deduper.models import AudioTrack
import music_deduper.scanner as scanner


def test_list_available_roots_returns_list(monkeypatch) -> None:
    monkeypatch.setattr(scanner.os, "name", "posix")
    assert scanner.list_available_roots() == ["/"]


def test_scan_audio_files_reads_supported_extensions_only(tmp_path, monkeypatch) -> None:
    root = tmp_path / "music"
    nested = root / "nested"
    nested.mkdir(parents=True)

    (root / "a.mp3").write_bytes(b"a")
    (nested / "b.flac").write_bytes(b"b")
    (nested / "ignore.txt").write_text("ignore", encoding="utf-8")

    calls: list[Path] = []
    progress_messages: list[str] = []

    def fake_read_audio_track(path: Path, scan_root: Path) -> AudioTrack:
        calls.append(path)
        return AudioTrack(
            path=path,
            root=scan_root,
            extension=path.suffix.lower(),
            size_bytes=path.stat().st_size,
            title=path.stem,
        )

    monkeypatch.setattr(scanner, "read_audio_track", fake_read_audio_track)

    tracks = scanner.scan_audio_files(root, progress=progress_messages.append)

    assert [track.path.name for track in tracks] == ["a.mp3", "b.flac"]
    assert [path.name for path in calls] == ["a.mp3", "b.flac"]
    assert progress_messages[0].startswith("开始扫描")
    assert progress_messages[-1] == "扫描结束，共识别到 2 首音频文件。"
```

- [ ] **4.3** Run the rule, scanner, model, and metadata tests together:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_models.py tests/test_audio_metadata.py tests/test_rules.py tests/test_scanner.py -v
```

---

## Task 5: Create server.py with FastAPI routes

**File:** `D:/MusicDeduplication/src/music_deduper/server.py`

**Goal:** Add a FastAPI application that exposes scan, group, keep-switch, execute, export, and static-file routes in one process.

**TDD:** Add API tests first with `TestClient`, then implement the server.

### Steps

- [ ] **5.1** Create `D:/MusicDeduplication/tests/test_server.py` with the exact API tests below:

```python
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fastapi.testclient import TestClient

from music_deduper.models import AudioTrack, DuplicateGroup
import music_deduper.server as server


def build_group(tmp_path: Path) -> DuplicateGroup:
    keep = AudioTrack(
        path=tmp_path / "keep.mp3",
        root=tmp_path,
        extension=".mp3",
        size_bytes=2000,
        title="Song",
        artist="Artist",
        album="Album",
        bitrate_kbps=320,
        has_cover=True,
        format_info="MP3 320 kbps",
    )
    duplicate = AudioTrack(
        path=tmp_path / "dup.mp3",
        root=tmp_path,
        extension=".mp3",
        size_bytes=1000,
        title="Song",
        artist="Artist",
        album="Album",
        bitrate_kbps=128,
        format_info="MP3 128 kbps",
    )
    keep.path.write_bytes(b"keep")
    duplicate.path.write_bytes(b"dup")
    return DuplicateGroup(
        key="Song / Artist",
        tracks=[keep, duplicate],
        keep_track=keep,
        duplicate_tracks=[duplicate],
    )


def test_roots_endpoint(monkeypatch) -> None:
    app = server.create_app()
    client = TestClient(app)
    monkeypatch.setattr(server, "list_available_roots", lambda: ["C:\\", "D:\\"])

    response = client.get("/api/roots")

    assert response.status_code == 200
    assert response.json() == {"roots": ["C:\\", "D:\\"]}


def test_groups_endpoint_returns_stats(tmp_path) -> None:
    app = server.create_app()
    client = TestClient(app)
    server.reset_state()
    server.APP_STATE.groups = [build_group(tmp_path)]
    server.APP_STATE.tracks = server.APP_STATE.groups[0].tracks

    response = client.get("/api/groups")

    payload = response.json()
    assert response.status_code == 200
    assert payload["stats"]["total_audio"] == 2
    assert payload["stats"]["duplicate_groups"] == 1
    assert payload["stats"]["files_to_clean"] == 1
    assert payload["groups"][0]["keep_track"]["path"].endswith("keep.mp3")


def test_keep_switch_endpoint_updates_group(tmp_path) -> None:
    app = server.create_app()
    client = TestClient(app)
    server.reset_state()
    group = build_group(tmp_path)
    server.APP_STATE.groups = [group]
    server.APP_STATE.tracks = group.tracks

    group_id = server.group_id_for(0, group)
    duplicate_path = str(group.duplicate_tracks[0].path)

    response = client.put(f"/api/groups/{group_id}/keep", json={"track_path": duplicate_path})

    payload = response.json()
    assert response.status_code == 200
    assert payload["keep_track"]["path"] == duplicate_path
    assert payload["duplicate_tracks"][0]["path"].endswith("keep.mp3")


def test_export_endpoint_returns_json_file(tmp_path) -> None:
    app = server.create_app()
    client = TestClient(app)
    server.reset_state()
    group = build_group(tmp_path)
    server.APP_STATE.groups = [group]
    server.APP_STATE.tracks = group.tracks
    server.APP_STATE.scan_root = str(tmp_path)

    response = client.get("/api/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
```

- [ ] **5.2** Run the API tests to establish the failing baseline:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_server.py -v
```
- [ ] **5.3** Create `D:/MusicDeduplication/src/music_deduper/server.py` with the exact FastAPI implementation below:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import re
import shutil
import threading
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dedupe import default_backup_dir, default_rule_states, find_duplicate_groups, human_size
from .models import AudioTrack, DuplicateGroup
from .scanner import list_available_roots, scan_audio_files

STATIC_DIR = Path(__file__).with_name("static")
REPORT_DIR = Path.cwd() / "reports"


class RootsResponse(BaseModel):
    roots: list[str]


class ScanRequest(BaseModel):
    path: str


class ScanStartResponse(BaseModel):
    task_id: str


class ProgressResponse(BaseModel):
    message: str = ""
    processed_files: int = 0


class TrackResponse(BaseModel):
    path: str
    relative_path: str
    title: str
    artist: str
    album: str
    bitrate_kbps: int | None
    duration_seconds: float | None
    has_cover: bool
    metadata_source: str
    year: int | None
    genre: str
    track_number: int | None
    format_info: str
    size_bytes: int
    warnings: list[str]


class GroupResponse(BaseModel):
    id: str
    key: str
    duplicate_count: int
    reclaimable_bytes: int
    reclaimable_human: str
    keep_track: TrackResponse
    duplicate_tracks: list[TrackResponse]
    tracks: list[TrackResponse]


class ScanStatusResponse(BaseModel):
    status: str
    progress: ProgressResponse
    groups: list[GroupResponse]
    log: list[str]
    error: str | None = None


class StatsArtistResponse(BaseModel):
    name: str
    duplicate_count: int
    reclaimable_bytes: int


class StatsResponse(BaseModel):
    total_audio: int
    duplicate_groups: int
    files_to_clean: int
    reclaimable_bytes: int
    reclaimable_human: str
    artists: list[StatsArtistResponse]


class GroupsResponse(BaseModel):
    stats: StatsResponse
    groups: list[GroupResponse]


class KeepRequest(BaseModel):
    track_path: str


class StopResponse(BaseModel):
    status: str


class ExecuteRequest(BaseModel):
    group_ids: list[str] = Field(default_factory=list)
    backup_dir: str = Field(default_factory=lambda: str(default_backup_dir()))


class ExecuteItemResponse(BaseModel):
    source_path: str
    destination_path: str


class ExecuteResponse(BaseModel):
    moved_count: int
    moved_files: list[ExecuteItemResponse]
    backup_root: str


@dataclass(slots=True)
class ScanTaskState:
    task_id: str
    root: Path
    status: str = "scanning"
    progress_message: str = "等待扫描"
    processed_files: int = 0
    tracks: list[AudioTrack] = field(default_factory=list)
    groups: list[DuplicateGroup] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    error: str | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


@dataclass(slots=True)
class AppState:
    tasks: dict[str, ScanTaskState] = field(default_factory=dict)
    tracks: list[AudioTrack] = field(default_factory=list)
    groups: list[DuplicateGroup] = field(default_factory=list)
    scan_root: str = ""
    rule_states: list = field(default_factory=default_rule_states)
    lock: threading.Lock = field(default_factory=threading.Lock)


APP_STATE = AppState()


def reset_state() -> None:
    global APP_STATE
    APP_STATE = AppState()


def create_app() -> FastAPI:
    app = FastAPI(title="Music Deduplication", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/roots", response_model=RootsResponse)
    def get_roots() -> RootsResponse:
        return RootsResponse(roots=list_available_roots())

    @app.post("/api/scan", response_model=ScanStartResponse)
    def start_scan(request: ScanRequest) -> ScanStartResponse:
        root = Path(request.path).expanduser()
        if not root.exists():
            raise HTTPException(status_code=404, detail="Scan path does not exist")

        task_id = uuid.uuid4().hex
        task = ScanTaskState(task_id=task_id, root=root)
        thread = threading.Thread(target=_run_scan_task, args=(task,), daemon=True)
        task.thread = thread

        with APP_STATE.lock:
            APP_STATE.tasks[task_id] = task
            APP_STATE.scan_root = str(root)

        thread.start()
        return ScanStartResponse(task_id=task_id)

    @app.get("/api/scan/{task_id}/status", response_model=ScanStatusResponse)
    def get_scan_status(task_id: str) -> ScanStatusResponse:
        task = _get_task(task_id)
        return ScanStatusResponse(
            status=task.status,
            progress=ProgressResponse(message=task.progress_message, processed_files=task.processed_files),
            groups=_serialize_groups(task.groups),
            log=task.log,
            error=task.error,
        )

    @app.post("/api/scan/{task_id}/stop", response_model=StopResponse)
    def stop_scan(task_id: str) -> StopResponse:
        task = _get_task(task_id)
        task.stop_event.set()
        task.status = "stopped"
        task.progress_message = "停止请求已发送"
        task.log.append("停止请求已发送")
        return StopResponse(status="stopped")

    @app.get("/api/groups", response_model=GroupsResponse)
    def get_groups(
        search: str = Query(default=""),
        artist: str = Query(default=""),
    ) -> GroupsResponse:
        filtered = _filter_groups(APP_STATE.groups, search=search, artist=artist)
        return GroupsResponse(stats=_build_stats(filtered, APP_STATE.tracks), groups=_serialize_groups(filtered))

    @app.get("/api/groups/{group_id}", response_model=GroupResponse)
    def get_group(group_id: str) -> GroupResponse:
        group = _find_group(group_id)
        index = APP_STATE.groups.index(group)
        return _serialize_group(index, group)

    @app.put("/api/groups/{group_id}/keep", response_model=GroupResponse)
    def update_keep_track(group_id: str, request: KeepRequest) -> GroupResponse:
        group = _find_group(group_id)
        selected = next((track for track in group.tracks if str(track.path) == request.track_path), None)
        if selected is None:
            raise HTTPException(status_code=404, detail="Track not found in group")

        group.keep_track = selected
        group.duplicate_tracks = [track for track in group.tracks if track.path != selected.path]
        index = APP_STATE.groups.index(group)
        return _serialize_group(index, group)

    @app.post("/api/execute", response_model=ExecuteResponse)
    def execute_dedupe(request: ExecuteRequest) -> ExecuteResponse:
        target_groups = [group for index, group in enumerate(APP_STATE.groups) if group_id_for(index, group) in request.group_ids]
        backup_root = Path(request.backup_dir).expanduser()
        backup_root.mkdir(parents=True, exist_ok=True)
        timestamp_root = backup_root / f"backup_{datetime.now():%Y%m%d_%H%M%S}"
        timestamp_root.mkdir(parents=True, exist_ok=True)

        moved_files: list[ExecuteItemResponse] = []
        for group in target_groups:
            for track in group.duplicate_tracks:
                destination = timestamp_root / track.relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                final_destination = _dedupe_destination(destination)
                shutil.move(str(track.path), str(final_destination))
                moved_files.append(
                    ExecuteItemResponse(
                        source_path=str(track.path),
                        destination_path=str(final_destination),
                    )
                )

        APP_STATE.tracks = [track for track in APP_STATE.tracks if track.path.exists()]
        APP_STATE.groups = find_duplicate_groups(APP_STATE.tracks, APP_STATE.rule_states)

        return ExecuteResponse(
            moved_count=len(moved_files),
            moved_files=moved_files,
            backup_root=str(timestamp_root),
        )

    @app.get("/api/export")
    def export_report() -> FileResponse:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "scan_root": APP_STATE.scan_root,
            "groups": [
                {
                    "id": group_id_for(index, group),
                    "key": group.key,
                    "keep_path": str(group.keep_track.path),
                    "duplicate_paths": [str(track.path) for track in group.duplicate_tracks],
                    "reclaimable_bytes": group.reclaimable_bytes,
                }
                for index, group in enumerate(APP_STATE.groups)
            ],
        }
        report_path = REPORT_DIR / f"dedupe_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return FileResponse(report_path, filename=report_path.name, media_type="application/json")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def _run_scan_task(task: ScanTaskState) -> None:
    def on_progress(message: str) -> None:
        task.progress_message = message
        task.log.append(message)
        match = re.search(r"已分析 (\d+) 首音频", message)
        if match:
            task.processed_files = int(match.group(1))

    try:
        tracks = scan_audio_files(task.root, progress=on_progress, stop_event=task.stop_event)
        groups = find_duplicate_groups(tracks, APP_STATE.rule_states)
        task.tracks = tracks
        task.groups = groups
        if task.stop_event.is_set():
            task.status = "stopped"
        else:
            task.status = "completed"
        task.progress_message = f"扫描完成，共识别 {len(tracks)} 首音频文件"

        with APP_STATE.lock:
            APP_STATE.tracks = tracks
            APP_STATE.groups = groups
            APP_STATE.scan_root = str(task.root)
    except Exception as exc:  # pragma: no cover
        task.status = "error"
        task.error = str(exc)
        task.progress_message = "扫描失败"
        task.log.append(f"错误: {exc}")


def _get_task(task_id: str) -> ScanTaskState:
    task = APP_STATE.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def group_id_for(index: int, group: DuplicateGroup) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", group.key.lower()).strip("-")
    return f"group-{index}-{slug or 'duplicate'}"


def _find_group(group_id: str) -> DuplicateGroup:
    for index, group in enumerate(APP_STATE.groups):
        if group_id_for(index, group) == group_id:
            return group
    raise HTTPException(status_code=404, detail="Group not found")


def _serialize_track(track: AudioTrack) -> TrackResponse:
    return TrackResponse(
        path=str(track.path),
        relative_path=track.relative_path,
        title=track.title,
        artist=track.artist,
        album=track.album,
        bitrate_kbps=track.bitrate_kbps,
        duration_seconds=track.duration_seconds,
        has_cover=track.has_cover,
        metadata_source=track.metadata_source,
        year=track.year,
        genre=track.genre,
        track_number=track.track_number,
        format_info=track.format_info,
        size_bytes=track.size_bytes,
        warnings=track.warnings,
    )


def _serialize_group(index: int, group: DuplicateGroup) -> GroupResponse:
    return GroupResponse(
        id=group_id_for(index, group),
        key=group.key,
        duplicate_count=len(group.duplicate_tracks),
        reclaimable_bytes=group.reclaimable_bytes,
        reclaimable_human=human_size(group.reclaimable_bytes),
        keep_track=_serialize_track(group.keep_track),
        duplicate_tracks=[_serialize_track(track) for track in group.duplicate_tracks],
        tracks=[_serialize_track(track) for track in group.tracks],
    )


def _serialize_groups(groups: list[DuplicateGroup]) -> list[GroupResponse]:
    return [_serialize_group(index, group) for index, group in enumerate(groups)]


def _filter_groups(groups: list[DuplicateGroup], search: str, artist: str) -> list[DuplicateGroup]:
    search_text = search.strip().lower()
    artist_text = artist.strip().lower()
    filtered: list[DuplicateGroup] = []

    for group in groups:
        haystack = " ".join(
            [
                group.key,
                *[track.display_title for track in group.tracks],
                *[track.display_artist for track in group.tracks],
            ]
        ).lower()
        if search_text and search_text not in haystack:
            continue

        artists = {track.display_artist.lower() for track in group.tracks}
        if artist_text and artist_text not in artists:
            continue

        filtered.append(group)

    return filtered


def _build_stats(groups: list[DuplicateGroup], tracks: list[AudioTrack]) -> StatsResponse:
    files_to_clean = sum(len(group.duplicate_tracks) for group in groups)
    reclaimable_bytes = sum(group.reclaimable_bytes for group in groups)
    artist_totals: dict[str, StatsArtistResponse] = {}

    for group in groups:
        artist_name = group.keep_track.display_artist
        item = artist_totals.get(artist_name)
        if item is None:
            artist_totals[artist_name] = StatsArtistResponse(
                name=artist_name,
                duplicate_count=len(group.duplicate_tracks),
                reclaimable_bytes=group.reclaimable_bytes,
            )
        else:
            artist_totals[artist_name] = StatsArtistResponse(
                name=item.name,
                duplicate_count=item.duplicate_count + len(group.duplicate_tracks),
                reclaimable_bytes=item.reclaimable_bytes + group.reclaimable_bytes,
            )

    artists = sorted(artist_totals.values(), key=lambda item: item.duplicate_count, reverse=True)
    return StatsResponse(
        total_audio=len(tracks),
        duplicate_groups=len(groups),
        files_to_clean=files_to_clean,
        reclaimable_bytes=reclaimable_bytes,
        reclaimable_human=human_size(reclaimable_bytes),
        artists=artists,
    )


def _dedupe_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    index = 1
    while True:
        candidate = destination.with_stem(f"{destination.stem}_{index}")
        if not candidate.exists():
            return candidate
        index += 1


app = create_app()
```

- [ ] **5.4** Run the server tests after the implementation is added:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_server.py -v
```

---

## Task 6: Update main.py and __main__.py

**File:** `D:/MusicDeduplication/src/music_deduper/main.py` and `D:/MusicDeduplication/src/music_deduper/__main__.py`

**Goal:** Launch the FastAPI app with Uvicorn on port 8000 and open the browser automatically.

**TDD:** Not required. Verification is a smoke launch and an HTTP request.

### Steps

- [ ] **6.1** Overwrite `D:/MusicDeduplication/src/music_deduper/main.py` with the exact code below:

```python
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
```

- [ ] **6.2** Overwrite `D:/MusicDeduplication/src/music_deduper/__main__.py` with the exact code below:

```python
from .main import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **6.3** Smoke-test the new entrypoints:

```powershell
Set-Location D:/MusicDeduplication
python main.py
```

In a second terminal, verify the root page responds:

```powershell
Invoke-WebRequest http://127.0.0.1:8000 | Select-Object -ExpandProperty StatusCode
```

Also verify the module entrypoint:

```powershell
Set-Location D:/MusicDeduplication
python -m music_deduper
```

---

## Task 7: Create static/index.html

**File:** `D:/MusicDeduplication/src/music_deduper/static/index.html`

**Goal:** Add the full web UI shell with sidebar controls, stats, results area, scan log, and execute confirmation modal.

**TDD:** Not applicable for HTML structure. Validate by serving the page and checking the DOM loads.

### Steps

- [ ] **7.1** Create `D:/MusicDeduplication/src/music_deduper/static/index.html` with the exact HTML below:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Music Deduplication</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <div class="app-shell">
      <aside class="sidebar">
        <div class="panel">
          <h1 class="sidebar-title">Music Deduplication</h1>
          <p class="sidebar-subtitle">本地扫描、本地分析、本地清理。</p>
        </div>

        <section class="panel">
          <h2 class="panel-title">扫描目录</h2>
          <label class="field-label" for="rootSelect">盘符 / 目录</label>
          <div class="row">
            <select id="rootSelect" class="input"></select>
            <button id="chooseFolderButton" class="button button-secondary" type="button">文件夹</button>
          </div>
          <input id="folderInput" type="file" webkitdirectory directory hidden>
        </section>

        <section class="panel">
          <h2 class="panel-title">保留规则</h2>
          <div id="ruleList" class="rule-list"></div>
        </section>

        <section class="panel">
          <h2 class="panel-title">执行设置</h2>
          <label class="toggle">
            <input id="previewToggle" type="checkbox">
            <span>仅预览，不移动重复文件</span>
          </label>
          <label class="field-label" for="backupDirInput">备份目录</label>
          <input id="backupDirInput" class="input" type="text" placeholder="D:\MusicDeduplicationBackups">
        </section>

        <section class="panel actions">
          <button id="scanButton" class="button button-primary" type="button">开始扫描</button>
          <button id="stopButton" class="button button-secondary" type="button">停止扫描</button>
          <div class="progress-wrap">
            <div class="progress-meta">
              <span id="progressText">等待扫描</span>
              <span id="progressCount">0</span>
            </div>
            <div class="progress-bar">
              <div id="progressFill" class="progress-fill"></div>
            </div>
          </div>
        </section>
      </aside>

      <main class="content">
        <header class="content-header">
          <div>
            <h2 class="content-title">重复结果</h2>
            <p id="scanSummary" class="content-subtitle">尚未开始扫描。</p>
          </div>
          <button id="executeButton" class="button button-primary" type="button">执行去重</button>
        </header>

        <section class="stats-grid">
          <article class="stat-card">
            <span class="stat-label">总音频数</span>
            <strong id="totalAudioStat" class="stat-value">0</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">重复分组</span>
            <strong id="duplicateGroupsStat" class="stat-value">0</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">待清理文件</span>
            <strong id="filesToCleanStat" class="stat-value">0</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">预计释放空间</span>
            <strong id="reclaimableStat" class="stat-value">0 B</strong>
          </article>
        </section>

        <section class="toolbar panel">
          <div class="toolbar-group">
            <input id="searchInput" class="input" type="search" placeholder="搜索歌名或歌手">
            <select id="artistFilter" class="input">
              <option value="">全部歌手</option>
            </select>
          </div>
          <div class="toolbar-group">
            <button id="resortButton" class="button button-secondary" type="button">重新排序</button>
            <button id="exportButton" class="button button-secondary" type="button">导出报告</button>
          </div>
        </section>

        <section class="results panel">
          <div id="resultsEmpty" class="empty-state">扫描完成后将在这里显示重复分组。</div>
          <div id="resultsList" class="group-list"></div>
        </section>

        <section class="panel log-panel">
          <button id="logToggle" class="log-toggle" type="button" aria-expanded="false">扫描日志</button>
          <div id="logContent" class="log-content" hidden>
            <pre id="scanLog" class="log-output"></pre>
          </div>
        </section>
      </main>
    </div>

    <div id="executeModal" class="modal" hidden>
      <div class="modal-backdrop"></div>
      <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
        <h2 id="modalTitle" class="modal-title">确认执行去重</h2>
        <p id="modalBody" class="modal-body">确认将重复文件移动到备份目录。</p>
        <div class="modal-actions">
          <button id="cancelExecuteButton" class="button button-secondary" type="button">取消</button>
          <button id="confirmExecuteButton" class="button button-primary" type="button">确认执行</button>
        </div>
      </div>
    </div>

    <template id="groupTemplate">
      <article class="group-card">
        <button class="group-summary" type="button">
          <div>
            <h3 class="group-title"></h3>
            <p class="group-meta"></p>
          </div>
          <span class="group-reclaim"></span>
        </button>
        <div class="group-details" hidden></div>
      </article>
    </template>

    <template id="trackComparisonTemplate">
      <div class="comparison-grid">
        <section class="track-card track-card-keep">
          <header class="track-card-header">保留</header>
          <dl class="track-details"></dl>
          <button class="switch-keep button button-secondary" type="button">设为保留</button>
        </section>
        <section class="track-card track-card-duplicate">
          <header class="track-card-header">重复</header>
          <dl class="track-details"></dl>
          <button class="switch-keep button button-secondary" type="button">设为保留</button>
        </section>
      </div>
    </template>

    <script src="/app.js" defer></script>
  </body>
</html>
```

- [ ] **7.2** Verify the page shell renders through FastAPI:

```powershell
Set-Location D:/MusicDeduplication
python main.py
```

In a second terminal:

```powershell
Invoke-WebRequest http://127.0.0.1:8000 | Select-Object -ExpandProperty Content
```

---

## Task 8: Create static/style.css

**File:** `D:/MusicDeduplication/src/music_deduper/static/style.css`

**Goal:** Apply a minimalist neutral layout that matches the design spec and clearly differentiates keep vs duplicate states.

**TDD:** Not applicable. Verify visually in the browser after loading the static page.

### Steps

- [ ] **8.1** Create `D:/MusicDeduplication/src/music_deduper/static/style.css` with the exact CSS below:

```css
:root {
  --bg: #f9fafb;
  --panel: #ffffff;
  --text: #111827;
  --muted: #6b7280;
  --border: #e5e7eb;
  --primary: #111827;
  --secondary: #f3f4f6;
  --keep-bg: #dcfce7;
  --keep-text: #166534;
  --duplicate-bg: #fef3c7;
  --duplicate-text: #92400e;
  --shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
  --radius: 14px;
  --sidebar-width: 280px;
  --font: "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
}

button,
input,
select {
  font: inherit;
}

.app-shell {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  min-height: 100vh;
}

.sidebar {
  background: var(--panel);
  border-right: 1px solid var(--border);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.content {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow);
}

.sidebar-title,
.content-title,
.panel-title,
.modal-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.sidebar-subtitle,
.content-subtitle,
.field-label,
.group-meta,
.stat-label,
.modal-body,
.empty-state {
  color: var(--muted);
}

.field-label {
  display: block;
  margin: 10px 0 8px;
  font-size: 13px;
}

.row,
.toolbar,
.toolbar-group,
.modal-actions,
.progress-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.row {
  align-items: stretch;
}

.toolbar {
  justify-content: space-between;
  flex-wrap: wrap;
}

.toolbar-group {
  flex-wrap: wrap;
}

.content-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}

.input {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #ffffff;
  color: var(--text);
  padding: 0 12px;
}

.button {
  min-height: 42px;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 0 14px;
  cursor: pointer;
  transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
}

.button-primary {
  background: var(--primary);
  color: #ffffff;
}

.button-primary:hover {
  background: #1f2937;
}

.button-secondary {
  background: var(--secondary);
  color: var(--text);
  border-color: var(--border);
}

.button-secondary:hover {
  background: #e5e7eb;
}

.actions {
  margin-top: auto;
}

.progress-wrap {
  margin-top: 12px;
}

.progress-bar {
  margin-top: 6px;
  width: 100%;
  height: 8px;
  background: var(--secondary);
  border-radius: 999px;
  overflow: hidden;
}

.progress-fill {
  width: 0%;
  height: 100%;
  background: var(--primary);
  transition: width 180ms ease;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow);
}

.stat-value {
  display: block;
  margin-top: 8px;
  font-size: 28px;
  font-weight: 700;
}

.results {
  min-height: 320px;
}

.group-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.group-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
}

.group-summary {
  width: 100%;
  border: 0;
  background: #ffffff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px;
  text-align: left;
  cursor: pointer;
}

.group-title {
  margin: 0;
  font-size: 16px;
}

.group-reclaim {
  color: var(--muted);
  font-weight: 600;
  white-space: nowrap;
}

.group-details {
  border-top: 1px solid var(--border);
  padding: 16px;
  background: #fcfcfd;
}

.comparison-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.track-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
}

.track-card-keep {
  background: var(--keep-bg);
  color: var(--keep-text);
}

.track-card-duplicate {
  background: var(--duplicate-bg);
  color: var(--duplicate-text);
}

.track-card-header {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
}

.track-details {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px 12px;
  margin: 0 0 14px;
}

.track-details dt {
  font-weight: 600;
}

.track-details dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rule-item {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  background: #fafafa;
}

.rule-header {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.rule-actions {
  display: flex;
  gap: 6px;
}

.toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.log-panel {
  padding: 0;
  overflow: hidden;
}

.log-toggle {
  width: 100%;
  border: 0;
  background: #ffffff;
  padding: 16px;
  text-align: left;
  cursor: pointer;
  font-weight: 600;
}

.log-content {
  border-top: 1px solid var(--border);
}

.log-output {
  margin: 0;
  padding: 16px;
  min-height: 120px;
  max-height: 260px;
  overflow: auto;
  background: #f9fafb;
  color: var(--muted);
}

.modal {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  z-index: 30;
}

.modal-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(17, 24, 39, 0.28);
}

.modal-dialog {
  position: relative;
  width: min(480px, calc(100vw - 32px));
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 20px;
  box-shadow: 0 18px 50px rgba(17, 24, 39, 0.2);
}

.modal-body {
  margin: 12px 0 20px;
  line-height: 1.6;
}

.empty-state {
  padding: 48px 16px;
  text-align: center;
}

@media (max-width: 1024px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .comparison-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .content {
    padding: 16px;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .content-header {
    flex-direction: column;
    align-items: stretch;
  }
}
```

- [ ] **8.2** Load the page in the browser and confirm the layout and colors:

```powershell
Set-Location D:/MusicDeduplication
python main.py
```

---

## Task 9: Create static/app.js

**File:** `D:/MusicDeduplication/src/music_deduper/static/app.js`

**Goal:** Implement all frontend behaviors: scan lifecycle, polling, rendering, filtering, keep switching, export, execute, and rule ordering interactions.

**TDD:** Not browser-unit-tested in this phase. Verify through manual API-backed interaction against the FastAPI server.

### Steps

- [ ] **9.1** Create `D:/MusicDeduplication/src/music_deduper/static/app.js` with the exact JavaScript below:

```javascript
const state = {
  taskId: "",
  groups: [],
  stats: {
    total_audio: 0,
    duplicate_groups: 0,
    files_to_clean: 0,
    reclaimable_human: "0 B",
    artists: [],
  },
  pollingHandle: null,
  selectedRoot: "",
  selectedFolderPath: "",
  previewOnly: false,
  backupDir: "",
  rules: [
    { key: "metadata_complete", label: "信息更完整优先", enabled: true },
    { key: "higher_bitrate", label: "码率更高优先", enabled: true },
    { key: "has_cover", label: "带封面优先", enabled: true },
    { key: "larger_file", label: "文件更大优先", enabled: false },
    { key: "shorter_path", label: "路径更短优先", enabled: false },
  ],
};

const elements = {
  rootSelect: document.querySelector("#rootSelect"),
  chooseFolderButton: document.querySelector("#chooseFolderButton"),
  folderInput: document.querySelector("#folderInput"),
  ruleList: document.querySelector("#ruleList"),
  previewToggle: document.querySelector("#previewToggle"),
  backupDirInput: document.querySelector("#backupDirInput"),
  scanButton: document.querySelector("#scanButton"),
  stopButton: document.querySelector("#stopButton"),
  progressText: document.querySelector("#progressText"),
  progressCount: document.querySelector("#progressCount"),
  progressFill: document.querySelector("#progressFill"),
  scanSummary: document.querySelector("#scanSummary"),
  totalAudioStat: document.querySelector("#totalAudioStat"),
  duplicateGroupsStat: document.querySelector("#duplicateGroupsStat"),
  filesToCleanStat: document.querySelector("#filesToCleanStat"),
  reclaimableStat: document.querySelector("#reclaimableStat"),
  searchInput: document.querySelector("#searchInput"),
  artistFilter: document.querySelector("#artistFilter"),
  resortButton: document.querySelector("#resortButton"),
  exportButton: document.querySelector("#exportButton"),
  resultsEmpty: document.querySelector("#resultsEmpty"),
  resultsList: document.querySelector("#resultsList"),
  logToggle: document.querySelector("#logToggle"),
  logContent: document.querySelector("#logContent"),
  scanLog: document.querySelector("#scanLog"),
  executeButton: document.querySelector("#executeButton"),
  executeModal: document.querySelector("#executeModal"),
  modalBody: document.querySelector("#modalBody"),
  cancelExecuteButton: document.querySelector("#cancelExecuteButton"),
  confirmExecuteButton: document.querySelector("#confirmExecuteButton"),
  groupTemplate: document.querySelector("#groupTemplate"),
  trackComparisonTemplate: document.querySelector("#trackComparisonTemplate"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.blob();
}

function init() {
  bindEvents();
  renderRules();
  loadRoots();
  loadGroups();
}

function bindEvents() {
  elements.chooseFolderButton.addEventListener("click", () => elements.folderInput.click());
  elements.folderInput.addEventListener("change", onChooseFolder);
  elements.previewToggle.addEventListener("change", () => {
    state.previewOnly = elements.previewToggle.checked;
  });
  elements.backupDirInput.addEventListener("input", () => {
    state.backupDir = elements.backupDirInput.value.trim();
  });
  elements.scanButton.addEventListener("click", startScan);
  elements.stopButton.addEventListener("click", stopScan);
  elements.searchInput.addEventListener("input", loadGroups);
  elements.artistFilter.addEventListener("change", loadGroups);
  elements.resortButton.addEventListener("click", onResortGroups);
  elements.exportButton.addEventListener("click", exportReport);
  elements.executeButton.addEventListener("click", openExecuteModal);
  elements.cancelExecuteButton.addEventListener("click", closeExecuteModal);
  elements.confirmExecuteButton.addEventListener("click", executeDedupe);
  elements.logToggle.addEventListener("click", toggleLogPanel);
}

async function loadRoots() {
  const payload = await api("/api/roots");
  elements.rootSelect.innerHTML = "";
  payload.roots.forEach((root) => {
    const option = document.createElement("option");
    option.value = root;
    option.textContent = root;
    elements.rootSelect.appendChild(option);
  });
  if (payload.roots.length > 0) {
    state.selectedRoot = payload.roots[0];
    elements.rootSelect.value = state.selectedRoot;
  }
  elements.rootSelect.addEventListener("change", () => {
    state.selectedRoot = elements.rootSelect.value;
  });
}

function onChooseFolder(event) {
  const files = Array.from(event.target.files || []);
  if (files.length === 0) {
    return;
  }
  const first = files[0];
  const relative = first.webkitRelativePath || first.name;
  const topLevel = relative.split("/")[0];
  state.selectedFolderPath = `${topLevel}`;
  elements.rootSelect.innerHTML = `<option value="${state.selectedFolderPath}">${state.selectedFolderPath}</option>`;
  elements.rootSelect.value = state.selectedFolderPath;
}

function renderRules() {
  elements.ruleList.innerHTML = "";
  state.rules.forEach((rule, index) => {
    const item = document.createElement("div");
    item.className = "rule-item";
    item.innerHTML = `
      <div class="rule-header">
        <label>
          <input type="checkbox" ${rule.enabled ? "checked" : ""} data-action="toggle" data-index="${index}">
          <span>${index + 1}. ${rule.label}</span>
        </label>
        <div class="rule-actions">
          <button class="button button-secondary" type="button" data-action="up" data-index="${index}">上移</button>
          <button class="button button-secondary" type="button" data-action="down" data-index="${index}">下移</button>
        </div>
      </div>
    `;
    elements.ruleList.appendChild(item);
  });

  elements.ruleList.querySelectorAll("[data-action]").forEach((node) => {
    node.addEventListener("click", onRuleAction);
    if (node.type === "checkbox") {
      node.addEventListener("change", onRuleAction);
    }
  });
}

function onRuleAction(event) {
  const action = event.currentTarget.dataset.action;
  const index = Number(event.currentTarget.dataset.index);
  if (action === "toggle") {
    state.rules[index].enabled = event.currentTarget.checked;
    return;
  }
  if (action === "up" && index > 0) {
    [state.rules[index - 1], state.rules[index]] = [state.rules[index], state.rules[index - 1]];
  }
  if (action === "down" && index < state.rules.length - 1) {
    [state.rules[index + 1], state.rules[index]] = [state.rules[index], state.rules[index + 1]];
  }
  renderRules();
}

async function startScan() {
  const selectedPath = elements.rootSelect.value.trim();
  if (!selectedPath) {
    alert("请选择扫描目录");
    return;
  }

  const payload = await api("/api/scan", {
    method: "POST",
    body: JSON.stringify({ path: selectedPath }),
  });

  state.taskId = payload.task_id;
  elements.progressText.textContent = "扫描中";
  elements.progressCount.textContent = "0";
  elements.progressFill.style.width = "8%";
  appendLog(`开始扫描: ${selectedPath}`);
  startPolling();
}

function startPolling() {
  stopPolling();
  state.pollingHandle = window.setInterval(async () => {
    if (!state.taskId) {
      return;
    }
    const payload = await api(`/api/scan/${state.taskId}/status`);
    updateProgress(payload.progress);
    renderLog(payload.log);
    if (payload.status === "completed" || payload.status === "stopped") {
      stopPolling();
      await loadGroups();
      elements.scanSummary.textContent = `扫描结束，共识别 ${state.stats.total_audio} 首音频，发现 ${state.stats.duplicate_groups} 组重复。`;
    }
    if (payload.status === "error") {
      stopPolling();
      appendLog(`扫描失败: ${payload.error || "unknown error"}`);
      alert(payload.error || "扫描失败");
    }
  }, 1000);
}

function stopPolling() {
  if (state.pollingHandle) {
    window.clearInterval(state.pollingHandle);
    state.pollingHandle = null;
  }
}

async function stopScan() {
  if (!state.taskId) {
    return;
  }
  await api(`/api/scan/${state.taskId}/stop`, { method: "POST" });
  appendLog("已请求停止扫描。");
}

function updateProgress(progress) {
  const processed = progress.processed_files || 0;
  elements.progressText.textContent = progress.message || "扫描中";
  elements.progressCount.textContent = `${processed}`;
  const width = Math.min(95, 8 + processed);
  elements.progressFill.style.width = `${width}%`;
}

async function loadGroups() {
  const search = encodeURIComponent(elements.searchInput.value.trim());
  const artist = encodeURIComponent(elements.artistFilter.value.trim());
  const payload = await api(`/api/groups?search=${search}&artist=${artist}`);
  state.groups = payload.groups;
  state.stats = payload.stats;
  renderStats();
  renderArtistFilter();
  renderGroups();
}

function renderStats() {
  elements.totalAudioStat.textContent = String(state.stats.total_audio);
  elements.duplicateGroupsStat.textContent = String(state.stats.duplicate_groups);
  elements.filesToCleanStat.textContent = String(state.stats.files_to_clean);
  elements.reclaimableStat.textContent = state.stats.reclaimable_human;
}

function renderArtistFilter() {
  const currentValue = elements.artistFilter.value;
  const options = ['<option value="">全部歌手</option>'];
  state.stats.artists.forEach((artist) => {
    const selected = artist.name === currentValue ? "selected" : "";
    options.push(`<option value="${artist.name}" ${selected}>${artist.name}</option>`);
  });
  elements.artistFilter.innerHTML = options.join("");
}

function renderGroups() {
  elements.resultsList.innerHTML = "";
  elements.resultsEmpty.hidden = state.groups.length > 0;

  state.groups.forEach((group) => {
    const fragment = elements.groupTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".group-card");
    const summaryButton = fragment.querySelector(".group-summary");
    const title = fragment.querySelector(".group-title");
    const meta = fragment.querySelector(".group-meta");
    const reclaim = fragment.querySelector(".group-reclaim");
    const details = fragment.querySelector(".group-details");

    title.textContent = group.key;
    meta.textContent = `保留 1 首，重复 ${group.duplicate_count} 首`;
    reclaim.textContent = group.reclaimable_human;

    summaryButton.addEventListener("click", () => {
      const hidden = details.hasAttribute("hidden");
      if (hidden) {
        details.removeAttribute("hidden");
        renderGroupDetails(group, details);
      } else {
        details.setAttribute("hidden", "");
        details.innerHTML = "";
      }
    });

    card.dataset.groupId = group.id;
    elements.resultsList.appendChild(fragment);
  });
}

function renderGroupDetails(group, container) {
  container.innerHTML = "";
  group.tracks.forEach((track) => {
    const fragment = elements.trackComparisonTemplate.content.cloneNode(true);
    const cards = fragment.querySelectorAll(".track-card");
    const keepCard = cards[0];
    const duplicateCard = cards[1];
    const keepDetails = keepCard.querySelector(".track-details");
    const duplicateDetails = duplicateCard.querySelector(".track-details");
    const keepButton = keepCard.querySelector(".switch-keep");
    const duplicateButton = duplicateCard.querySelector(".switch-keep");

    const isKeep = track.path === group.keep_track.path;
    fillTrackDetails(keepDetails, isKeep ? track : group.keep_track);
    fillTrackDetails(duplicateDetails, isKeep ? group.duplicate_tracks[0] || track : track);

    keepButton.dataset.path = isKeep ? track.path : group.keep_track.path;
    duplicateButton.dataset.path = isKeep ? (group.duplicate_tracks[0] ? group.duplicate_tracks[0].path : track.path) : track.path;
    keepButton.dataset.groupId = group.id;
    duplicateButton.dataset.groupId = group.id;

    keepButton.addEventListener("click", onSwitchKeep);
    duplicateButton.addEventListener("click", onSwitchKeep);

    if (group.duplicate_tracks.length === 0) {
      duplicateCard.remove();
    }

    container.appendChild(fragment);
    return;
  });
}

function fillTrackDetails(container, track) {
  const rows = [
    ["标题", track.title || "(空)"],
    ["歌手", track.artist || "(空)"],
    ["专辑", track.album || "(空)"],
    ["码率", track.bitrate_kbps ? `${track.bitrate_kbps} kbps` : "-"],
    ["时长", track.duration_seconds ? `${track.duration_seconds.toFixed(1)} s` : "-"],
    ["封面", track.has_cover ? "有" : "无"],
    ["年份", track.year || "-"],
    ["流派", track.genre || "-"],
    ["轨道", track.track_number || "-"],
    ["格式", track.format_info || track.metadata_source || "-"],
    ["路径", track.relative_path],
  ];
  container.innerHTML = rows.map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`).join("");
}

async function onSwitchKeep(event) {
  const groupId = event.currentTarget.dataset.groupId;
  const trackPath = event.currentTarget.dataset.path;
  await api(`/api/groups/${groupId}/keep`, {
    method: "PUT",
    body: JSON.stringify({ track_path: trackPath }),
  });
  await loadGroups();
}

function onResortGroups() {
  state.groups.sort((left, right) => right.reclaimable_bytes - left.reclaimable_bytes);
  renderGroups();
}

async function exportReport() {
  const blob = await api("/api/export");
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "dedupe-report.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

function openExecuteModal() {
  if (state.previewOnly) {
    alert("当前处于仅预览模式，不会执行移动。");
    return;
  }
  const selectedCount = state.groups.length;
  elements.modalBody.textContent = `将处理 ${selectedCount} 个重复分组，并把重复文件移动到 ${elements.backupDirInput.value || "默认备份目录"}。`;
  elements.executeModal.hidden = false;
}

function closeExecuteModal() {
  elements.executeModal.hidden = true;
}

async function executeDedupe() {
  const groupIds = state.groups.map((group) => group.id);
  const backupDir = elements.backupDirInput.value.trim();
  const payload = await api("/api/execute", {
    method: "POST",
    body: JSON.stringify({
      group_ids: groupIds,
      backup_dir: backupDir,
    }),
  });
  appendLog(`执行去重完成，移动 ${payload.moved_count} 个文件到 ${payload.backup_root}`);
  closeExecuteModal();
  await loadGroups();
}

function toggleLogPanel() {
  const expanded = elements.logToggle.getAttribute("aria-expanded") === "true";
  elements.logToggle.setAttribute("aria-expanded", String(!expanded));
  if (expanded) {
    elements.logContent.hidden = true;
  } else {
    elements.logContent.hidden = false;
  }
}

function appendLog(message) {
  const lines = elements.scanLog.textContent ? `${elements.scanLog.textContent}\n${message}` : message;
  elements.scanLog.textContent = lines;
}

function renderLog(logLines) {
  elements.scanLog.textContent = logLines.join("\n");
}

document.addEventListener("DOMContentLoaded", init);
```

- [ ] **9.2** Start the server and manually verify the frontend flow:

```powershell
Set-Location D:/MusicDeduplication
python main.py
```

Manual verification sequence:

```text
1. Open http://127.0.0.1:8000
2. Confirm roots load into the dropdown
3. Start a scan and watch the progress text update every second
4. Expand a duplicate group and switch the keep track
5. Filter by search text and artist
6. Export the report
7. Execute dedupe and confirm the modal + refresh flow
```

---

## Task 10: End-to-end integration test

**File:** `D:/MusicDeduplication/tests/test_integration.py`

**Goal:** Add a minimal end-to-end HTTP integration test that confirms HTML serving and the empty API state before a scan.

**TDD:** This is the final regression check once the server and static files exist.

### Steps

- [ ] **10.1** Create `D:/MusicDeduplication/tests/test_integration.py` with the exact code below:

```python
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

    root_response = client.get("/")
    roots_response = client.get("/api/roots")
    groups_response = client.get("/api/groups")

    assert root_response.status_code == 200
    assert "text/html" in root_response.headers["content-type"]
    assert "<!doctype html>" in root_response.text.lower()

    assert roots_response.status_code == 200
    assert roots_response.json() == {"roots": ["C:\\", "D:\\"]}

    assert groups_response.status_code == 200
    assert groups_response.json()["stats"]["total_audio"] == 0
    assert groups_response.json()["stats"]["duplicate_groups"] == 0
    assert groups_response.json()["groups"] == []
```

- [ ] **10.2** Run the full test suite:

```powershell
Set-Location D:/MusicDeduplication
python -m pytest tests/test_models.py tests/test_audio_metadata.py tests/test_rules.py tests/test_scanner.py tests/test_server.py tests/test_integration.py -v
```

- [ ] **10.3** Run the final application smoke test after all code is in place:

```powershell
Set-Location D:/MusicDeduplication
pip install -e .
python main.py
```

In a second terminal, verify both the HTML app and API respond:

```powershell
Invoke-WebRequest http://127.0.0.1:8000 | Select-Object -ExpandProperty StatusCode
Invoke-WebRequest http://127.0.0.1:8000/api/roots | Select-Object -ExpandProperty Content
```
