from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from music_deduper.models import AudioTrack
from music_deduper.scanner import list_available_roots, scan_audio_files


class TestListAvailableRoots:
    def test_returns_list_of_strings(self) -> None:
        roots = list_available_roots()
        assert isinstance(roots, list)
        assert all(isinstance(r, str) for r in roots)
        assert len(roots) > 0

    @patch("music_deduper.scanner.os.name", "nt")
    def test_windows_returns_drive_letters(self) -> None:
        with patch("music_deduper.scanner.ctypes") as mock_ctypes:
            # 0b11100 = bits 2,3,4 set => C:, D:, E:
            mock_ctypes.windll.kernel32.GetLogicalDrives.return_value = 0b11100
            roots = list_available_roots()
            assert "C:\\" in roots
            assert "D:\\" in roots
            assert "E:\\" in roots
            assert len(roots) == 3


class TestScanAudioFiles:
    @patch.object(Path, "stat")
    def test_scan_finds_audio_files(self, mock_stat) -> None:
        """scan_audio_files should call read_audio_track for each audio file found."""
        fake_result = MagicMock()
        fake_result.st_size = 4000
        mock_stat.return_value = fake_result

        # Create a mock track that read_audio_track will return
        mock_track = AudioTrack(
            path=Path("D:/music/song.mp3"),
            root=Path("D:/music"),
            extension=".mp3",
            size_bytes=4000,
            title="Test Song",
            artist="Test Artist",
        )

        # Mock os.walk to return a known structure
        fake_walk = [
            ("D:/music", ["subdir"], ["song.mp3", "readme.txt", "photo.jpg"]),
            ("D:/music/subdir", [], ["another.flac", "notes.txt"]),
        ]

        with patch("music_deduper.scanner.os.walk", return_value=fake_walk):
            with patch("music_deduper.scanner.read_audio_track", return_value=mock_track) as mock_read:
                tracks = scan_audio_files(Path("D:/music"))

        assert len(tracks) == 2
        assert mock_read.call_count == 2
        # Verify the correct files were passed (sorted, only audio extensions)
        called_paths = [call[0][0] for call in mock_read.call_args_list]
        assert Path("D:/music/song.mp3") in called_paths
        assert Path("D:/music/subdir/another.flac") in called_paths

    @patch.object(Path, "stat")
    def test_scan_respects_stop_event(self, mock_stat) -> None:
        """scan_audio_files should stop early when stop_event is set."""
        fake_result = MagicMock()
        fake_result.st_size = 1000
        mock_stat.return_value = fake_result

        mock_track = AudioTrack(
            path=Path("D:/music/a.mp3"),
            root=Path("D:/music"),
            extension=".mp3",
            size_bytes=1000,
        )

        # Make os.walk yield multiple directories, then set stop_event
        stop_event = MagicMock()
        stop_event.is_set.side_effect = [False, False, True, True, True]

        fake_walk = [
            ("D:/music", ["dir1", "dir2"], ["a.mp3"]),
            ("D:/music/dir1", [], ["b.flac", "c.mp3"]),
            ("D:/music/dir2", [], ["d.ogg"]),
        ]

        messages = []
        with patch("music_deduper.scanner.os.walk", return_value=fake_walk):
            with patch("music_deduper.scanner.read_audio_track", return_value=mock_track) as mock_read:
                tracks = scan_audio_files(
                    Path("D:/music"),
                    progress=lambda m: messages.append(m),
                    stop_event=stop_event,
                )

        # Should have stopped early - not all files processed
        assert any("手动停止" in m for m in messages)

    @patch.object(Path, "stat")
    def test_scan_calls_progress_callback(self, mock_stat) -> None:
        """scan_audio_files should report progress via callback."""
        fake_result = MagicMock()
        fake_result.st_size = 2000
        mock_stat.return_value = fake_result

        mock_track = AudioTrack(
            path=Path("D:/music/s.mp3"),
            root=Path("D:/music"),
            extension=".mp3",
            size_bytes=2000,
        )

        fake_walk = [
            ("D:/music", [], ["s.mp3"]),
        ]

        messages = []
        with patch("music_deduper.scanner.os.walk", return_value=fake_walk):
            with patch("music_deduper.scanner.read_audio_track", return_value=mock_track):
                tracks = scan_audio_files(
                    Path("D:/music"),
                    progress=lambda m: messages.append(m),
                )

        assert len(messages) >= 2  # start + end messages at minimum
        assert any("开始扫描" in m for m in messages)
        assert any("扫描结束" in m for m in messages)
        assert any("识别到 1" in m for m in messages)

    @patch.object(Path, "stat")
    def test_scan_empty_directory(self, mock_stat) -> None:
        """scan_audio_files should return empty list for directory with no audio."""
        fake_walk = [
            ("D:/music", [], ["readme.txt", "image.png"]),
        ]

        with patch("music_deduper.scanner.os.walk", return_value=fake_walk):
            tracks = scan_audio_files(Path("D:/music"))

        assert len(tracks) == 0
