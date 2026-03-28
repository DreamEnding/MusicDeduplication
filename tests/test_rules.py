import sys
from pathlib import Path
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
        self.assertEqual(normalize_text("Hello - World (Live)"), "hello world live")

    def test_build_key_prefers_title_artist(self) -> None:
        track = AudioTrack(
            path=Path("A:/Song.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=1024,
            title="Blue Train",
            artist="John Coltrane",
            year=1958,
            genre="Jazz",
            track_number=1,
            format_info="MP3 320 kbps",
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
            year=2023,
            genre="Pop",
            track_number=1,
            format_info="MP3 128 kbps",
            bitrate_kbps=128,
            has_cover=False,
        )
        high = AudioTrack(
            path=Path("A:/high.mp3"),
            root=Path("A:/"),
            extension=".mp3",
            size_bytes=2_000_000,
            title="Song",
            artist="Singer",
            album="Album",
            year=2023,
            genre="Pop",
            track_number=1,
            format_info="MP3 320 kbps",
            bitrate_kbps=320,
            has_cover=True,
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
            year=2006,
            genre="Pop",
            track_number=7,
            format_info="MP3 320 kbps",
            bitrate_kbps=320,
            has_cover=True,
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
