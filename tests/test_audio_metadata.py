from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from unittest.mock import MagicMock, patch
import pytest

from music_deduper.audio_metadata import read_audio_track
from music_deduper.models import AudioTrack


def _make_path(stem: str = "test", ext: str = ".mp3") -> Path:
    return Path(f"D:/music/{stem}{ext}")


def _fake_stat(size: int = 5000):
    m = MagicMock()
    m.st_size = size
    return m


# ---------- MP3 ID3 tags ----------

class TestMP3Metadata:
    @patch.object(Path, "stat")
    def test_extracts_id3v2_tags(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        mutagen_file = MagicMock()
        mutagen_file.info.bitrate = 320000
        mutagen_file.info.length = 210.5
        tags = {
            "TIT2": MagicMock(text=["Song Title"]),
            "TPE1": MagicMock(text=["Artist Name"]),
            "TALB": MagicMock(text=["Album Name"]),
            "TDRC": MagicMock(text=["2023"]),
            "TCON": MagicMock(text=["Rock"]),
            "TRCK": MagicMock(text=["5"]),
        }
        mutagen_file.tags = tags
        mutagen_file.get.return_value = None  # no cover art

        with patch("music_deduper.audio_metadata.MutagenFile", return_value=mutagen_file):
            track = read_audio_track(_make_path(), Path("D:/music"))

        assert isinstance(track, AudioTrack)
        assert track.title == "Song Title"
        assert track.artist == "Artist Name"
        assert track.album == "Album Name"
        assert track.year == 2023
        assert track.genre == "Rock"
        assert track.track_number == 5
        assert track.bitrate_kbps == 320
        assert track.duration_seconds == pytest.approx(210.5)
        assert track.has_cover is False
        assert track.format_info != ""

    @patch.object(Path, "stat")
    def test_extracts_cover_art(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        apic_mock = MagicMock()
        apic_mock.data = b'\xff\xd8\xff\xe0'
        apic_mock.mime = "image/jpeg"
        mutagen_file = MagicMock()
        mutagen_file.info.bitrate = 128000
        mutagen_file.info.length = 180.0
        mutagen_file.tags = {
            "TIT2": MagicMock(text=["Cover Song"]),
            "APIC": apic_mock,
        }
        mutagen_file.get.return_value = apic_mock

        with patch("music_deduper.audio_metadata.MutagenFile", return_value=mutagen_file):
            track = read_audio_track(_make_path(), Path("D:/music"))

        assert track.has_cover is True

    @patch.object(Path, "stat")
    def test_handles_missing_tags_gracefully(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        mutagen_file = MagicMock()
        mutagen_file.info.bitrate = 0
        mutagen_file.info.length = 0
        mutagen_file.tags = {}

        with patch("music_deduper.audio_metadata.MutagenFile", return_value=mutagen_file):
            track = read_audio_track(_make_path(), Path("D:/music"))

        assert track.title == ""
        assert track.artist == ""
        assert track.year is None
        assert track.genre == ""
        assert track.track_number is None

    @patch.object(Path, "stat")
    def test_handles_exception_during_parsing(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        with patch("music_deduper.audio_metadata.MutagenFile", side_effect=Exception("corrupt file")):
            track = read_audio_track(_make_path(), Path("D:/music"))

        assert isinstance(track, AudioTrack)
        assert track.title == ""
        assert len(track.warnings) > 0

    @patch.object(Path, "stat")
    def test_handles_mutagen_returning_none(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        with patch("music_deduper.audio_metadata.MutagenFile", return_value=None):
            track = read_audio_track(_make_path(), Path("D:/music"))

        assert isinstance(track, AudioTrack)
        assert track.title == ""
        assert track.metadata_source == ""


# ---------- MP4 / M4A ----------

class TestMP4Metadata:
    @patch.object(Path, "stat")
    def test_extracts_mp4_copyright_prefix_tags(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        mutagen_file = MagicMock()
        mutagen_file.info.bitrate = 256000
        mutagen_file.info.length = 195.3
        mutagen_file.tags = {
            "\u00a9nam": ["M4A Title"],
            "\u00a9ART": ["M4A Artist"],
            "\u00a9alb": ["M4A Album"],
            "\u00a9day": ["2024"],
            "\u00a9gen": ["Pop"],
            "trkn": [(3, 12)],
        }
        mutagen_file.get.return_value = None

        with patch("music_deduper.audio_metadata.MutagenFile", return_value=mutagen_file):
            track = read_audio_track(_make_path("test", ".m4a"), Path("D:/music"))

        assert track.title == "M4A Title"
        assert track.artist == "M4A Artist"
        assert track.album == "M4A Album"
        assert track.year == 2024
        assert track.genre == "Pop"
        assert track.track_number == 3


# ---------- WMA ----------

class TestWMAMetadata:
    @patch.object(Path, "stat")
    def test_extracts_wma_tags(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        mutagen_file = MagicMock()
        mutagen_file.info.bitrate = 192000
        mutagen_file.info.length = 240.0
        mutagen_file.tags = {
            "Title": ["WMA Song"],
            "Author": ["WMA Artist"],
            "WM/AlbumTitle": ["WMA Album"],
            "WM/Year": ["2022"],
            "WM/Genre": ["Jazz"],
            "WM/TrackNumber": ["8"],
        }
        mutagen_file.get.return_value = None

        with patch("music_deduper.audio_metadata.MutagenFile", return_value=mutagen_file):
            track = read_audio_track(_make_path("test", ".wma"), Path("D:/music"))

        assert track.title == "WMA Song"
        assert track.artist == "WMA Artist"
        assert track.album == "WMA Album"
        assert track.year == 2022
        assert track.genre == "Jazz"
        assert track.track_number == 8


# ---------- OGG / FLAC (Vorbis comments) ----------

class TestVorbisMetadata:
    @patch.object(Path, "stat")
    def test_extracts_vorbis_comments(self, mock_stat) -> None:
        mock_stat.return_value = _fake_stat()

        mutagen_file = MagicMock()
        mutagen_file.info.bitrate = 0
        mutagen_file.info.length = 300.0
        mutagen_file.tags = {
            "title": ["OGG Title"],
            "artist": ["OGG Artist"],
            "album": ["OGG Album"],
            "date": ["2021"],
            "genre": ["Classical"],
            "tracknumber": ["2"],
        }
        mutagen_file.get.return_value = None

        with patch("music_deduper.audio_metadata.MutagenFile", return_value=mutagen_file):
            track = read_audio_track(_make_path("test", ".ogg"), Path("D:/music"))

        assert track.title == "OGG Title"
        assert track.artist == "OGG Artist"
        assert track.album == "OGG Album"
        assert track.year == 2021
        assert track.genre == "Classical"
        assert track.track_number == 2
