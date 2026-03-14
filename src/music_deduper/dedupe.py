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
_TITLE_PREFIX = "title::"
_FILE_PREFIX = "file::"


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
    ordered = sorted(signatures, key=_signature_priority)
    return ordered[0] if ordered else ""


def build_dedupe_signatures(track: AudioTrack) -> set[str]:
    signatures: set[str] = set()
    title = normalize_text(track.title)
    artist = normalize_text(track.artist)
    stem = normalize_text(track.filename_stem)

    if title and artist:
        signatures.add(f"{_PAIR_PREFIX}{canonical_pair_key(title, artist)}")
        signatures.add(f"{_TITLE_PREFIX}{title}")

    if title and not artist:
        signatures.add(f"{_TITLE_PREFIX}{title}")

    inferred_pair = infer_pair_from_filename(track.filename_stem)
    if inferred_pair:
        left, right = inferred_pair
        signatures.add(f"{_PAIR_PREFIX}{canonical_pair_key(left, right)}")

    if stem:
        signatures.add(f"{_FILE_PREFIX}{stem}")

    return signatures


def infer_pair_from_filename(filename_stem: str) -> tuple[str, str] | None:
    raw = re.sub(r"\s+", " ", filename_stem).strip()
    if not raw:
        return None
    parts = [part.strip() for part in re.split(r"\s*[-—－_]+\s*", raw) if part.strip()]
    if len(parts) != 2:
        return None
    left = normalize_text(parts[0])
    right = normalize_text(parts[1])
    if not left or not right:
        return None
    if left == right:
        return None
    if len(left) < 2 or len(right) < 2:
        return None
    return left, right


def canonical_pair_key(left: str, right: str) -> str:
    ordered = sorted([left, right])
    return "::".join(ordered)


def describe_group_key(tracks: list[AudioTrack]) -> str:
    signatures = [build_dedupe_signatures(track) for track in tracks]
    frequency: dict[str, int] = {}
    for signature_set in signatures:
        for signature in signature_set:
            frequency[signature] = frequency.get(signature, 0) + 1

    shared = [signature for signature, count in frequency.items() if count >= 2]
    if not shared:
        return tracks[0].display_title

    best = min(shared, key=_signature_priority)
    if best.startswith(_PAIR_PREFIX):
        left, right = best[len(_PAIR_PREFIX) :].split("::", 1)
        return f"{left} / {right}"
    if best.startswith(_TITLE_PREFIX):
        return best[len(_TITLE_PREFIX) :]
    return best[len(_FILE_PREFIX) :]


def _signature_priority(signature: str) -> tuple[int, int, str]:
    if signature.startswith(_PAIR_PREFIX):
        return (0, -len(signature), signature)
    if signature.startswith(_TITLE_PREFIX):
        return (1, -len(signature), signature)
    return (2, -len(signature), signature)


def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", value)
    value = re.sub(r"\b(feat|ft|ver|version|live|demo|remaster)\b\.?", " ", value)
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
