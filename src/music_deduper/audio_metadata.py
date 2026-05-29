from __future__ import annotations

import base64
import hashlib
import struct
from dataclasses import replace
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import ID3

from .models import AudioTrack

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".wma", ".dsf", ".alac"}

# ---------------------------------------------------------------------------
# Cover art cache: key -> (image_bytes, mime_type)
# ---------------------------------------------------------------------------

_cover_cache: dict[str, tuple[bytes, str]] = {}


def cache_cover(path: Path, image_bytes: bytes, mime_type: str) -> str:
    key = hashlib.md5(str(path).encode()).hexdigest()[:12]
    _cover_cache[key] = (image_bytes, mime_type)
    return key


def get_cover(key: str) -> tuple[bytes, str] | None:
    return _cover_cache.get(key)


def cover_key_for_path(path: Path) -> str:
    return hashlib.md5(str(path).encode()).hexdigest()[:12]


def clear_cover_cache() -> None:
    _cover_cache.clear()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def read_audio_track(path: Path, root: Path) -> AudioTrack:
    """Read metadata from *path* and return a fully-populated AudioTrack."""
    base = AudioTrack(
        path=path,
        root=root,
        extension=path.suffix.lower(),
        size_bytes=path.stat().st_size,
    )

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
        if ext in {".flac", ".ogg", ".wav"}:
            return _enrich_vorbis(base, mf)
        return _enrich_generic(base, mf)
    except Exception as exc:
        base.warnings.append(f"标签解析失败: {exc}")
        return base


# ---------------------------------------------------------------------------
# Helper: extract common audio info
# ---------------------------------------------------------------------------

def _extract_audio_info(mf) -> dict:
    bitrate_kbps = None
    duration_seconds = None
    format_info = ""

    if hasattr(mf, "info"):
        info = mf.info
        raw_bitrate = getattr(info, "bitrate", 0) or 0
        bitrate_kbps = int(raw_bitrate // 1000) if raw_bitrate else None

        raw_length = getattr(info, "length", None)
        if raw_length is not None and raw_length > 0:
            duration_seconds = float(raw_length)

        sample_rate = getattr(info, "sample_rate", 0)
        if not isinstance(sample_rate, (int, float)):
            sample_rate = 0
        bits_per_sample = getattr(info, "bits_per_sample", 0)
        if not isinstance(bits_per_sample, (int, float)):
            bits_per_sample = 0

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
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Cover art extraction helpers
# ---------------------------------------------------------------------------

def _try_cache_cover(path: Path, image_bytes: bytes | None, mime_type: str | None) -> bool:
    if image_bytes and mime_type:
        cache_cover(path, image_bytes, mime_type)
        return True
    return bool(image_bytes)


def _extract_id3_cover(tags, path: Path) -> bool:
    apic = tags.get("APIC")
    if apic is None:
        return False
    try:
        _try_cache_cover(path, apic.data, getattr(apic, "mime", "image/jpeg") or "image/jpeg")
    except Exception:
        pass
    return True


def _extract_mp4_cover(tags, path: Path) -> bool:
    covr = tags.get("covr")
    if covr is None or not isinstance(covr, list) or not covr:
        return False
    try:
        image_bytes = bytes(covr[0])
        fmt_id = covr.format if hasattr(covr, "format") else 0x0D
        mime = "image/png" if fmt_id == 0x0E else "image/jpeg"
        _try_cache_cover(path, image_bytes, mime)
    except Exception:
        pass
    return True


def _extract_wma_cover(tags, path: Path) -> bool:
    pic = tags.get("WM/Picture")
    if pic is None or not isinstance(pic, list) or not pic:
        return False
    try:
        pict = pic[0]
        image_bytes = pict.value if hasattr(pict, "value") else bytes(pict)
        mime = getattr(pict, "mime_type", "image/jpeg") or "image/jpeg"
        _try_cache_cover(path, image_bytes, mime)
    except Exception:
        pass
    return True


def _extract_vorbis_cover(tags, path: Path) -> bool:
    mbp = tags.get("metadata_block_picture")
    if mbp is None or not isinstance(mbp, list) or not mbp:
        return False
    try:
        raw = base64.b64decode(mbp[0])
        if len(raw) < 8:
            return True
        mime_len = struct.unpack(">I", raw[4:8])[0]
        if len(raw) < 8 + mime_len:
            return True
        mime = raw[8:8 + mime_len].decode("ascii", errors="replace")
        desc_len = struct.unpack(">I", raw[8 + mime_len:12 + mime_len])[0]
        data_offset = 12 + mime_len + desc_len
        data_len = struct.unpack(">I", raw[data_offset:data_offset + 4])[0]
        image_bytes = raw[data_offset + 4:data_offset + 4 + data_len]
        _try_cache_cover(path, image_bytes, mime)
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# Lyrics detection helpers
# ---------------------------------------------------------------------------

def _detect_id3_lyrics(tags) -> bool:
    return bool(tags.get("USLT")) or bool(tags.get("SYLT"))


def _extract_id3_lyrics_text(tags) -> str:
    """Extract lyrics text from USLT tag."""
    uslt = tags.get("USLT")
    if uslt is None:
        return ""
    try:
        text = getattr(uslt, "text", None)
        if text and isinstance(text, list) and text:
            return str(text[0]).strip()
    except Exception:
        pass
    return ""


def _detect_mp4_lyrics(tags) -> bool:
    val = tags.get("©lyr")
    return bool(val and isinstance(val, list) and any(v.strip() for v in val if isinstance(v, str)))


def _extract_mp4_lyrics_text(tags) -> str:
    val = tags.get("©lyr")
    if val and isinstance(val, list) and val:
        return str(val[0]).strip()
    return ""


def _detect_wma_lyrics(tags) -> bool:
    val = tags.get("WM/Lyrics")
    return bool(val and isinstance(val, list) and val)


def _extract_wma_lyrics_text(tags) -> str:
    val = tags.get("WM/Lyrics")
    if val and isinstance(val, list) and val:
        return str(val[0]).strip()
    return ""


def _detect_vorbis_lyrics(tags) -> bool:
    for key in ("LYRICS", "UNSYNCEDLYRICS", "lyrics"):
        val = tags.get(key)
        if val and isinstance(val, list) and any(v.strip() for v in val if isinstance(v, str)):
            return True
    return False


def _extract_vorbis_lyrics_text(tags) -> str:
    for key in ("LYRICS", "UNSYNCEDLYRICS", "lyrics"):
        val = tags.get(key)
        if val and isinstance(val, list) and val:
            text = str(val[0]).strip()
            if text:
                return text
    return ""


# ---------------------------------------------------------------------------
# MP3 (ID3)
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
    has_cover = _extract_id3_cover(tags, track.path)
    has_lyrics = _detect_id3_lyrics(tags)

    return replace(
        track, title=title, artist=artist, album=album, year=year,
        genre=genre, track_number=track_number, has_cover=has_cover,
        has_lyrics=has_lyrics, metadata_source="ID3", **info,
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
# MP4 / M4A
# ---------------------------------------------------------------------------

def _enrich_mp4(track: AudioTrack, mf) -> AudioTrack:
    tags = mf.tags or {}
    info = _extract_audio_info(mf)

    title = _mp4_text(tags, "©nam")
    artist = _mp4_text(tags, "©ART")
    album = _mp4_text(tags, "©alb")
    year = _safe_int(_mp4_text(tags, "©day"))
    genre = _mp4_text(tags, "©gen")
    track_number = _mp4_track(tags.get("trkn"))
    has_cover = _extract_mp4_cover(tags, track.path)
    has_lyrics = _detect_mp4_lyrics(tags)

    return replace(
        track, title=title, artist=artist, album=album, year=year,
        genre=genre, track_number=track_number, has_cover=has_cover,
        has_lyrics=has_lyrics, metadata_source="MP4", **info,
    )


def _mp4_text(tags: dict, key: str) -> str:
    val = tags.get(key)
    if val and isinstance(val, list) and val:
        return str(val[0]).strip()
    return ""


def _mp4_track(value) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, list) and value:
            value = value[0]
        return int(value[0])
    except (TypeError, IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# WMA
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
    has_cover = _extract_wma_cover(tags, track.path)
    has_lyrics = _detect_wma_lyrics(tags)

    return replace(
        track, title=title, artist=artist, album=album, year=year,
        genre=genre, track_number=track_number, has_cover=has_cover,
        has_lyrics=has_lyrics, metadata_source="WMA", **info,
    )


def _wma_text(tags: dict, key: str) -> str:
    val = tags.get(key)
    if val and isinstance(val, list) and val:
        return str(val[0]).strip()
    return ""


# ---------------------------------------------------------------------------
# Vorbis (FLAC, OGG)
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
    has_cover = _extract_vorbis_cover(tags, track.path)
    has_lyrics = _detect_vorbis_lyrics(tags)

    source = "FLAC" if track.extension == ".flac" else "OGG"
    return replace(
        track, title=title, artist=artist, album=album, year=year,
        genre=genre, track_number=track_number, has_cover=has_cover,
        has_lyrics=has_lyrics, metadata_source=source, **info,
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

    for key in ("title", "TIT2", "©nam", "Title"):
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

    for key in ("artist", "TPE1", "©ART", "Author"):
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

    for key in ("album", "TALB", "©alb", "WM/AlbumTitle"):
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

    return replace(track, title=title, artist=artist, album=album, metadata_source="generic", **info)


# ---------------------------------------------------------------------------
# DSF
# ---------------------------------------------------------------------------

def _enrich_dsf(track: AudioTrack) -> AudioTrack:
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
    has_lyrics = False

    try:
        with open(track.path, "rb") as f:
            magic = f.read(4)
            if magic != b"DSD ":
                track.warnings.append("DSF: missing DSD magic bytes")
                return replace(track, metadata_source="DSF")

            dsd_chunk_size = struct.unpack("<Q", f.read(8))[0]
            if dsd_chunk_size > 12:
                f.seek(dsd_chunk_size - 12, 1)

            fmt_magic = f.read(4)
            if fmt_magic != b"fmt ":
                track.warnings.append("DSF: missing fmt chunk")
                return replace(track, metadata_source="DSF")

            fmt_chunk_size = struct.unpack("<Q", f.read(8))[0]
            fmt_data = f.read(fmt_chunk_size - 12)

            if len(fmt_data) < 32:
                track.warnings.append("DSF: fmt chunk truncated")
                return replace(track, metadata_source="DSF")

            (_, _, _, channel_count, sampling_freq, bits_per_sample) = (
                struct.unpack_from("<6I", fmt_data, 0)
            )
            sample_count = struct.unpack_from("<Q", fmt_data, 24)[0]

            if sampling_freq > 0:
                duration_seconds = sample_count / sampling_freq
                bitrate_kbps = int(sampling_freq * bits_per_sample * channel_count / 1000)

            sr_mhz = sampling_freq / 1_000_000
            format_info = f"DSD, {sr_mhz:.1f} MHz, {bits_per_sample}-bit"

    except Exception as exc:
        track.warnings.append(f"DSF header parse error: {exc}")
        return replace(track, metadata_source="DSF")

    try:
        id3_tags = ID3(track.path)
        title = _id3_text(id3_tags, "TIT2")
        artist = _id3_text(id3_tags, "TPE1")
        album = _id3_text(id3_tags, "TALB")
        year = _safe_int(_id3_text(id3_tags, "TDRC"))
        genre = _id3_text(id3_tags, "TCON")
        track_number = _safe_int(_id3_text(id3_tags, "TRCK"))
        has_cover = _extract_id3_cover(id3_tags, track.path)
        has_lyrics = _detect_id3_lyrics(id3_tags)
    except Exception:
        pass

    return replace(
        track, title=title, artist=artist, album=album, year=year,
        genre=genre, track_number=track_number, has_cover=has_cover,
        has_lyrics=has_lyrics, metadata_source="DSF",
        bitrate_kbps=bitrate_kbps, duration_seconds=duration_seconds,
        format_info=format_info,
    )
