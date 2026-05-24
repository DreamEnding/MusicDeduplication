from __future__ import annotations

import struct
from dataclasses import replace
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import ID3

from .models import AudioTrack

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".wma", ".dsf", ".alac"}


def read_audio_track(path: Path, root: Path) -> AudioTrack:
    """Read metadata from *path* and return a fully-populated AudioTrack."""
    base = AudioTrack(
        path=path,
        root=root,
        extension=path.suffix.lower(),
        size_bytes=path.stat().st_size,
    )

    # DSF needs custom binary parsing — mutagen does not support it.
    if base.extension == ".dsf":
        return _enrich_dsf(base)

    try:
        mf = MutagenFile(path)
    except Exception as exc:
        base.warnings.append(f"Mutagen 解析失败: {exc}")
        return base

    if mf is None:
        return base

    ext = base.extension
    try:
        if ext == ".mp3":
            return _enrich_mp3(base, mf)
        if ext in {".m4a", ".mp4", ".aac", ".alac"}:
            return _enrich_mp4(base, mf)
        if ext == ".wma":
            return _enrich_wma(base, mf)
        # FLAC, OGG, and other Vorbis-comment formats
        if ext in {".flac", ".ogg", ".wav"}:
            return _enrich_vorbis(base, mf)
        # Fallback: generic attempt
        return _enrich_generic(base, mf)
    except Exception as exc:
        base.warnings.append(f"标签解析失败: {exc}")
        return base


# ---------------------------------------------------------------------------
# Helper: extract common audio info from any mutagen File object
# ---------------------------------------------------------------------------

def _extract_audio_info(mf) -> dict:
    """Return a dict with bitrate_kbps, duration_seconds, format_info."""
    bitrate_kbps = None
    duration_seconds = None
    format_info = ""

    if hasattr(mf, "info"):
        info = mf.info
        # Bitrate
        raw_bitrate = getattr(info, "bitrate", 0) or 0
        bitrate_kbps = int(raw_bitrate // 1000) if raw_bitrate else None

        # Duration
        raw_length = getattr(info, "length", None)
        if raw_length is not None and raw_length > 0:
            duration_seconds = float(raw_length)

        # Sample rate for lossless formats
        sample_rate = getattr(info, "sample_rate", 0)
        if not isinstance(sample_rate, (int, float)):
            sample_rate = 0
        bits_per_sample = getattr(info, "bits_per_sample", 0)
        if not isinstance(bits_per_sample, (int, float)):
            bits_per_sample = 0

        # Build format_info
        parts: list[str] = []
        if bitrate_kbps:
            parts.append(f"{bitrate_kbps} kbps")
        if sample_rate:
            parts.append(f"{sample_rate} Hz")
        if bits_per_sample:
            parts.append(f"{bits_per_sample}-bit")
        format_info = ", ".join(parts) if parts else ""

    return {
        "bitrate_kbps": bitrate_kbps,
        "duration_seconds": duration_seconds,
        "format_info": format_info,
    }


def _safe_int(value: str | None) -> int | None:
    """Parse a string to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# MP3 (ID3) enrichment
# ---------------------------------------------------------------------------

def _enrich_mp3(track: AudioTrack, mf) -> AudioTrack:
    tags = mf.tags or {}
    info = _extract_audio_info(mf)

    title = _id3_text(tags, "TIT2")
    artist = _id3_text(tags, "TPE1")
    album = _id3_text(tags, "TALB")
    year = _safe_int(_id3_text(tags, "TDRC"))
    genre = _id3_text(tags, "TCON")
    track_number = _safe_int(_id3_text(tags, "TRCK"))
    has_cover = tags.get("APIC") is not None or mf.get("APIC") is not None

    return replace(
        track,
        title=title,
        artist=artist,
        album=album,
        year=year,
        genre=genre,
        track_number=track_number,
        has_cover=has_cover,
        metadata_source="ID3",
        **info,
    )


def _id3_text(tags: dict, key: str) -> str:
    frame = tags.get(key)
    if frame is None:
        return ""
    text = getattr(frame, "text", None)
    if text and isinstance(text, list) and text:
        return str(text[0]).strip()
    return ""


# ---------------------------------------------------------------------------
# MP4 / M4A enrichment (copyright-prefix tag keys)
# ---------------------------------------------------------------------------

def _enrich_mp4(track: AudioTrack, mf) -> AudioTrack:
    tags = mf.tags or {}
    info = _extract_audio_info(mf)

    title = _mp4_text(tags, "\u00a9nam")
    artist = _mp4_text(tags, "\u00a9ART")
    album = _mp4_text(tags, "\u00a9alb")
    year = _safe_int(_mp4_text(tags, "\u00a9day"))
    genre = _mp4_text(tags, "\u00a9gen")
    track_number = _mp4_track(tags.get("trkn"))
    has_cover = tags.get("covr") is not None or mf.get("covr") is not None

    return replace(
        track,
        title=title,
        artist=artist,
        album=album,
        year=year,
        genre=genre,
        track_number=track_number,
        has_cover=has_cover,
        metadata_source="MP4",
        **info,
    )


def _mp4_text(tags: dict, key: str) -> str:
    val = tags.get(key)
    if val and isinstance(val, list) and val:
        return str(val[0]).strip()
    return ""


def _mp4_track(value) -> int | None:
    """MP4 trkn is stored as a tuple (track, total) or list [(track, total)]."""
    if value is None:
        return None
    try:
        if isinstance(value, list) and value:
            value = value[0]
        return int(value[0])
    except (TypeError, IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# WMA enrichment (ASF / WM- prefix tags)
# ---------------------------------------------------------------------------

def _enrich_wma(track: AudioTrack, mf) -> AudioTrack:
    tags = mf.tags or {}
    info = _extract_audio_info(mf)

    title = _wma_text(tags, "Title")
    artist = _wma_text(tags, "Author")
    album = _wma_text(tags, "WM/AlbumTitle")
    year = _safe_int(_wma_text(tags, "WM/Year"))
    genre = _wma_text(tags, "WM/Genre")
    track_number = _safe_int(_wma_text(tags, "WM/TrackNumber"))
    # WMA cover: look for WM/Picture
    has_cover = tags.get("WM/Picture") is not None

    return replace(
        track,
        title=title,
        artist=artist,
        album=album,
        year=year,
        genre=genre,
        track_number=track_number,
        has_cover=has_cover,
        metadata_source="WMA",
        **info,
    )


def _wma_text(tags: dict, key: str) -> str:
    val = tags.get(key)
    if val and isinstance(val, list) and val:
        return str(val[0]).strip()
    return ""


# ---------------------------------------------------------------------------
# Vorbis-comment enrichment (FLAC, OGG)
# ---------------------------------------------------------------------------

def _enrich_vorbis(track: AudioTrack, mf) -> AudioTrack:
    tags = mf.tags or {}
    info = _extract_audio_info(mf)

    title = _vorbis_text(tags, "title")
    artist = _vorbis_text(tags, "artist")
    album = _vorbis_text(tags, "album")
    year = _safe_int(_vorbis_text(tags, "date"))
    genre = _vorbis_text(tags, "genre")
    track_number = _safe_int(_vorbis_text(tags, "tracknumber"))
    has_cover = tags.get("metadata_block_picture") is not None

    source = "FLAC" if track.extension == ".flac" else "OGG"
    return replace(
        track,
        title=title,
        artist=artist,
        album=album,
        year=year,
        genre=genre,
        track_number=track_number,
        has_cover=has_cover,
        metadata_source=source,
        **info,
    )


def _vorbis_text(tags: dict, key: str) -> str:
    val = tags.get(key)
    if val and isinstance(val, list) and val:
        return str(val[0]).strip()
    return ""


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

def _enrich_generic(track: AudioTrack, mf) -> AudioTrack:
    info = _extract_audio_info(mf)
    tags = mf.tags or {}
    title = ""
    artist = ""
    album = ""

    # Try common keys regardless of format
    for key in ("title", "TIT2", "\u00a9nam", "Title"):
        val = tags.get(key)
        if val:
            if isinstance(val, list) and val:
                title = str(val[0]).strip()
            else:
                t = getattr(val, "text", None)
                if t and isinstance(t, list) and t:
                    title = str(t[0]).strip()
            if title:
                break

    for key in ("artist", "TPE1", "\u00a9ART", "Author"):
        val = tags.get(key)
        if val:
            if isinstance(val, list) and val:
                artist = str(val[0]).strip()
            else:
                t = getattr(val, "text", None)
                if t and isinstance(t, list) and t:
                    artist = str(t[0]).strip()
            if artist:
                break

    for key in ("album", "TALB", "\u00a9alb", "WM/AlbumTitle"):
        val = tags.get(key)
        if val:
            if isinstance(val, list) and val:
                album = str(val[0]).strip()
            else:
                t = getattr(val, "text", None)
                if t and isinstance(t, list) and t:
                    album = str(t[0]).strip()
            if album:
                break

    return replace(
        track,
        title=title,
        artist=artist,
        album=album,
        metadata_source="generic",
        **info,
    )


# ---------------------------------------------------------------------------
# DSF (DSD Stream File) enrichment — custom binary parsing + ID3v2 tags
# ---------------------------------------------------------------------------

def _enrich_dsf(track: AudioTrack) -> AudioTrack:
    """Parse DSF headers manually and read ID3v2 tags via mutagen."""
    bitrate_kbps = None
    duration_seconds = None
    format_info = ""
    title = ""
    artist = ""
    album = ""
    year = None
    genre = ""
    track_number = None
    has_cover = False

    try:
        with open(track.path, "rb") as f:
            # -- DSD chunk -------------------------------------------------------
            magic = f.read(4)
            if magic != b"DSD ":
                track.warnings.append("DSF: missing DSD magic bytes")
                return replace(track, metadata_source="DSF")

            dsd_chunk_size = struct.unpack("<Q", f.read(8))[0]
            # Skip remainder of DSD chunk (chunk_size includes the 12 bytes
            # already read: 4 magic + 8 size)
            if dsd_chunk_size > 12:
                f.seek(dsd_chunk_size - 12, 1)

            # -- fmt chunk -------------------------------------------------------
            fmt_magic = f.read(4)
            if fmt_magic != b"fmt ":
                track.warnings.append("DSF: missing fmt chunk")
                return replace(track, metadata_source="DSF")

            fmt_chunk_size = struct.unpack("<Q", f.read(8))[0]
            fmt_data = f.read(fmt_chunk_size - 12)  # 4 magic + 8 size already read

            if len(fmt_data) < 32:
                # We need at least 24 bytes of u32 fields + 8 bytes u64 sample_count
                track.warnings.append("DSF: fmt chunk truncated")
                return replace(track, metadata_source="DSF")

            # fmt chunk layout (all little-endian):
            #   format_version  (u32)  offset 0
            #   format_id       (u32)  offset 4
            #   channel_type    (u32)  offset 8
            #   channel_count   (u32)  offset 12
            #   sampling_freq   (u32)  offset 16
            #   bits_per_sample (u32)  offset 20
            #   sample_count    (u64)  offset 24
            (_, _, _, channel_count, sampling_freq, bits_per_sample) = (
                struct.unpack_from("<6I", fmt_data, 0)
            )
            sample_count = struct.unpack_from("<Q", fmt_data, 24)[0]

            if sampling_freq > 0:
                duration_seconds = sample_count / sampling_freq
                bitrate_kbps = int(
                    sampling_freq * bits_per_sample * channel_count / 1000
                )

            # Human-readable format info
            sr_mhz = sampling_freq / 1_000_000
            format_info = f"DSD, {sr_mhz:.1f} MHz, {bits_per_sample}-bit"

    except Exception as exc:
        track.warnings.append(f"DSF header parse error: {exc}")
        return replace(track, metadata_source="DSF")

    # -- ID3v2 tags (DSF embeds ID3v2 at the end of the file) ----------------
    try:
        id3_tags = ID3(track.path)
        title = _id3_text(id3_tags, "TIT2")
        artist = _id3_text(id3_tags, "TPE1")
        album = _id3_text(id3_tags, "TALB")
        year = _safe_int(_id3_text(id3_tags, "TDRC"))
        genre = _id3_text(id3_tags, "TCON")
        track_number = _safe_int(_id3_text(id3_tags, "TRCK"))
        has_cover = id3_tags.get("APIC") is not None
    except Exception:
        # No ID3 tags or unreadable — that is acceptable for DSF
        pass

    return replace(
        track,
        title=title,
        artist=artist,
        album=album,
        year=year,
        genre=genre,
        track_number=track_number,
        has_cover=has_cover,
        metadata_source="DSF",
        bitrate_kbps=bitrate_kbps,
        duration_seconds=duration_seconds,
        format_info=format_info,
    )
