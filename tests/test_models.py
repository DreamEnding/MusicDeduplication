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
