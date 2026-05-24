"""AI-assisted deduplication using an OpenAI-compatible LLM API."""
from __future__ import annotations

import json
import re
from collections.abc import Callable

import httpx

from .dedupe import describe_group_key, select_preferred_track
from .models import AudioTrack, DuplicateGroup, RuleState

BATCH_SIZE = 50
MAX_BATCHES = 20

_SYSTEM_PROMPT = (
    "You are a music library deduplication assistant. "
    "Given a numbered list of audio tracks with metadata, "
    "identify which tracks are duplicates of the same song. "
    'Return a JSON array where each element has "group" (array of track indices) '
    'and "keep" (the index of the best-quality version to keep). '
    "Consider title, artist, album, bitrate, duration, and file size. "
    'Songs with different versions (e.g. "TV size" vs "full", "live" vs "studio", '
    '"remix" vs "original") should be in SEPARATE groups. '
    "If no duplicates exist, return an empty array. "
    "Return ONLY valid JSON, no explanation."
)


def ai_find_duplicate_groups(
    tracks: list[AudioTrack],
    rule_states: list[RuleState],
    api_url: str,
    api_key: str,
    model: str,
    progress: Callable[[str], None] | None = None,
) -> list[DuplicateGroup]:
    progress = progress or (lambda _: None)

    if not tracks:
        return []

    groups: list[DuplicateGroup] = []
    batches = _make_batches(tracks)
    total_batches = len(batches)

    for batch_idx, (batch_tracks, offset) in enumerate(batches):
        progress(f"AI 分析第 {batch_idx + 1}/{total_batches} 批 ({len(batch_tracks)} 首)...")
        prompt = _format_tracks_for_prompt(batch_tracks)

        try:
            response_text = _call_llm(api_url, api_key, model, prompt)
        except Exception as exc:
            progress(f"AI API 调用失败 (第 {batch_idx + 1} 批): {exc}")
            continue

        batch_groups = _parse_llm_response(response_text, batch_tracks, offset, rule_states)
        groups.extend(batch_groups)

    progress(f"AI 分析完成，识别到 {len(groups)} 组重复。")
    return groups


def _make_batches(tracks: list[AudioTrack]) -> list[tuple[list[AudioTrack], int]]:
    result: list[tuple[list[AudioTrack], int]] = []
    limit = min(MAX_BATCHES, (len(tracks) + BATCH_SIZE - 1) // BATCH_SIZE)
    for i in range(limit):
        start = i * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(tracks))
        result.append((tracks[start:end], start))
    return result


def _format_tracks_for_prompt(tracks: list[AudioTrack]) -> str:
    lines: list[str] = []
    for i, t in enumerate(tracks):
        parts = [
            f"[{i}]",
            f"title={t.display_title}",
            f"artist={t.display_artist}",
            f"album={t.display_album}",
        ]
        if t.bitrate_kbps:
            parts.append(f"bitrate={t.bitrate_kbps}kbps")
        if t.duration_seconds:
            parts.append(f"duration={t.duration_seconds:.1f}s")
        parts.append(f"size={t.size_bytes}")
        parts.append(f"file={t.filename_stem}")
        if t.has_cover:
            parts.append("cover=yes")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _call_llm(api_url: str, api_key: str, model: str, prompt: str) -> str:
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    return content


def _parse_llm_response(
    text: str,
    tracks: list[AudioTrack],
    offset: int,
    rule_states: list[RuleState],
) -> list[DuplicateGroup]:
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    groups: list[DuplicateGroup] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        indices = item.get("group", [])
        keep_idx = item.get("keep")

        if not isinstance(indices, list) or len(indices) < 2:
            continue

        # Convert to global indices and validate
        global_indices = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(tracks):
                global_indices.append(offset + idx)

        if len(global_indices) < 2:
            continue

        members = []
        for gi in global_indices:
            # Safety: track may not exist at global index
            if 0 <= gi < len(tracks) + offset:
                # Use the original tracks list relative to offset
                local_idx = gi - offset
                if 0 <= local_idx < len(tracks):
                    members.append(tracks[local_idx])

        if len(members) < 2:
            continue

        keep_track = select_preferred_track(members, rule_states)
        duplicates = [t for t in members if t.path != keep_track.path]

        groups.append(
            DuplicateGroup(
                key=describe_group_key(members),
                tracks=sorted(members, key=lambda t: t.relative_path.lower()),
                keep_track=keep_track,
                duplicate_tracks=duplicates,
            )
        )

    return groups
