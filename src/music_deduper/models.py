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
