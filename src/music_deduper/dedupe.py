from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .models import AudioTrack, DuplicateGroup, RuleState


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    key: str
    label: str
    description: str

    def score(self, track: AudioTrack) -> tuple[int, ...]:
        match self.key:
            case "metadata_complete":
                return (1 if track.has_core_metadata else 0, track.metadata_filled_count)
            case "higher_bitrate":
                return (track.bitrate_kbps or 0, track.size_bytes // 1024)
            case "has_cover":
                return (1 if track.has_cover else 0,)
            case "larger_file":
                return (track.size_bytes,)
            case "shorter_path":
                return (-track.path_depth, -len(track.relative_path))
            case _:
                return (0,)


RULE_DEFINITIONS = [
    RuleDefinition("metadata_complete", "信息更完整优先", "优先保留标题、歌手、专辑填写更完整的文件。"),
    RuleDefinition("higher_bitrate", "码率更高优先", "优先保留 kbps 更高的文件。"),
    RuleDefinition("has_cover", "带封面优先", "优先保留包含专辑封面的文件。"),
    RuleDefinition("larger_file", "文件更大优先", "作为音质兜底规则，优先保留体积更大的文件。"),
    RuleDefinition("shorter_path", "路径更短优先", "当前面规则相同，优先保留目录层级更浅的文件。"),
]

RULE_MAP = {rule.key: rule for rule in RULE_DEFINITIONS}
_PAIR_PREFIX = "pair::"


def default_rule_states() -> list[RuleState]:
    return [
        RuleState(key=rule.key, label=rule.label, description=rule.description, enabled=rule.key in {"metadata_complete", "higher_bitrate", "has_cover"})
        for rule in RULE_DEFINITIONS
    ]


def find_duplicate_groups(tracks: list[AudioTrack], rule_states: list[RuleState]) -> list[DuplicateGroup]:
    if not tracks:
        return []

    signature_sets = [build_dedupe_signatures(track) for track in tracks]
    parent = list(range(len(tracks)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    signature_owner: dict[str, int] = {}
    for index, signatures in enumerate(signature_sets):
        for signature in signatures:
            previous = signature_owner.get(signature)
            if previous is None:
                signature_owner[signature] = index
            else:
                union(index, previous)

    grouped_indices: dict[int, list[int]] = {}
    for index in range(len(tracks)):
        grouped_indices.setdefault(find(index), []).append(index)

    groups: list[DuplicateGroup] = []
    for indexes in grouped_indices.values():
        if len(indexes) < 2:
            continue
        members = [tracks[index] for index in indexes]
        keep_track = select_preferred_track(members, rule_states)
        duplicates = [track for track in members if track.path != keep_track.path]
        group_key = describe_group_key(members)
        groups.append(
            DuplicateGroup(
                key=group_key,
                tracks=sorted(members, key=lambda item: item.relative_path.lower()),
                keep_track=keep_track,
                duplicate_tracks=duplicates,
            )
        )

    groups.sort(key=lambda group: group.reclaimable_bytes, reverse=True)
    return groups


def build_dedupe_key(track: AudioTrack) -> str:
    signatures = build_dedupe_signatures(track)
    ordered = sorted(signatures, key=len, reverse=True)
    return ordered[0] if ordered else ""


# ---- Version tag extraction ----

# Common version/variant suffixes in Chinese and English
_VERSION_PATTERNS = re.compile(
    r"""(?ix)
    \s*[-—－]?\s*                          # optional separator
    (?:                                    # version tag group:
        \( (?:                             # parenthesized form
            TV\s*(?:size|ver|version)?      # TV size / TV ver
          | 纯音[乐]?版?                     # 纯音/纯音乐/纯音版
          | 伴奏
          | instrumental
          | acapella
          | live
          | demo
          | remix
          | cover
          | karaoke
          | off\s*vocal
          | bgm
          | \S*版                          # any Chinese version tag ending in 版
          | \S*version                      # English version
          | \S*ver\.?                       # ver / ver.
          | \S*edit                         # edit / radio edit
          | \S*mix                          # mix / remix
          | remaster(?:ed)?
        ) \)
      | \[ (?:                             # bracketed form
            TV\s*(?:size|ver|version)?
          | 纯音[乐]?版?
          | 伴奏
          | instrumental
          | acapella
          | live
          | demo
          | remix
          | cover
          | karaoke
          | off\s*vocal
          | bgm
          | \S*版
          | \S*version
          | \S*ver\.?
          | \S*edit
          | \S*mix
          | remaster(?:ed)?
        ) \]
      | (?:                                 # bare form (no brackets)
            TV\s*(?:size|ver|version)?
          | 纯音[乐]?版?
          | 伴奏
          | instrumental
          | acapella
          | live
          | demo
          | remix
          | cover
          | karaoke
          | off\s*vocal
          | bgm
          | remaster(?:ed)?
        ) \s*$
    )
    """
)


def _extract_version_and_base(raw: str) -> tuple[str, str]:
    """Split raw text into (base_title, version_tag).

    Returns (base, version) where version is "" if no version tag found.
    """
    match = _VERSION_PATTERNS.search(raw)
    if not match:
        return raw.strip(), ""
    version = match.group(0).strip(" ()[]")
    base = raw[: match.start()].strip()
    return base, version.lower()


def build_dedupe_signatures(track: AudioTrack) -> set[str]:
    signatures: set[str] = set()

    # --- From metadata: title + artist ---
    raw_title = track.title or ""
    raw_artist = track.artist or ""

    if raw_title and raw_artist:
        base_title, version = _extract_version_and_base(raw_title)
        norm_title = normalize_text(base_title)
        norm_artist = normalize_text(raw_artist)
        if norm_title and norm_artist:
            # Signature includes version so "TV版" won't match "纯音版"
            norm_version = normalize_text(version) if version else ""
            sig = f"{_PAIR_PREFIX}{norm_artist}::{norm_title}"
            if norm_version:
                sig += f"::{norm_version}"
            signatures.add(sig)

    # --- From filename: try "Artist - Title" pattern ---
    inferred = infer_pair_from_filename(track.filename_stem)
    if inferred:
        artist_part, title_part, version_part = inferred
        norm_artist = normalize_text(artist_part)
        norm_title = normalize_text(title_part)
        norm_version = normalize_text(version_part) if version_part else ""
        if norm_artist and norm_title and norm_artist != norm_title:
            # Canonical sort since we don't know which is artist vs title
            ordered = sorted([norm_artist, norm_title])
            sig = f"{_PAIR_PREFIX}{ordered[0]}::{ordered[1]}"
            if norm_version:
                sig += f"::{norm_version}"
            signatures.add(sig)

    return signatures


def infer_pair_from_filename(filename_stem: str) -> tuple[str, str, str] | None:
    """Parse 'Artist - Title' from filename, extracting version tag.

    Returns (artist, title, version) or None.
    """
    raw = re.sub(r"\s+", " ", filename_stem).strip()
    if not raw:
        return None
    parts = [part.strip() for part in re.split(r"\s*[-—－]+\s*", raw) if part.strip()]
    if len(parts) != 2:
        return None
    artist_raw = parts[0]
    title_raw = parts[1]
    if len(artist_raw) < 2 or len(title_raw) < 2:
        return None

    base_title, version = _extract_version_and_base(title_raw)
    norm_artist = normalize_text(artist_raw)
    norm_title = normalize_text(base_title)
    if not norm_artist or not norm_title:
        return None
    if norm_artist == norm_title:
        return None
    return artist_raw, base_title, version


def describe_group_key(tracks: list[AudioTrack]) -> str:
    first = tracks[0]
    title = first.title or first.display_title
    artist = first.artist or ""
    if title and artist:
        return f"{artist} - {title}"
    return title or first.display_title


def normalize_text(value: str) -> str:
    value = value.lower().strip()
    # Strip bracket/paren content that is NOT version-related (feat/ft etc.)
    value = re.sub(r"\b(feat|ft)\.?\s*", " ", value)
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def select_preferred_track(tracks: list[AudioTrack], rule_states: list[RuleState]) -> AudioTrack:
    enabled_rules = [RULE_MAP[state.key] for state in rule_states if state.enabled and state.key in RULE_MAP]
    if not enabled_rules:
        enabled_rules = [RULE_MAP["metadata_complete"], RULE_MAP["higher_bitrate"], RULE_MAP["has_cover"]]

    best_score = None
    candidates: list[AudioTrack] = []
    for track in tracks:
        score = tuple(part for rule in enabled_rules for part in rule.score(track))
        if best_score is None or score > best_score:
            best_score = score
            candidates = [track]
        elif score == best_score:
            candidates.append(track)

    return min(candidates, key=_stable_tie_breaker)


def _stable_tie_breaker(track: AudioTrack) -> tuple[int, int, str]:
    return (track.path_depth, len(track.relative_path), track.relative_path.lower())


def human_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def default_backup_dir() -> Path:
    return Path.home() / "MusicDeduplicationBackups"
