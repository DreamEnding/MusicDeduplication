from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct

from .models import AudioTrack

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".wma"}

_BITRATE_TABLE = {
    ("MPEG1", "Layer3"): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    ("MPEG2", "Layer3"): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}


def read_audio_track(path: Path, root: Path) -> AudioTrack:
    base = AudioTrack(
        path=path,
        root=root,
        extension=path.suffix.lower(),
        size_bytes=path.stat().st_size,
    )
    try:
        if base.extension == ".mp3":
            return _read_mp3_metadata(base)
        if base.extension == ".flac":
            return _read_flac_metadata(base)
        return base
    except Exception as exc:  # pragma: no cover
        base.warnings.append(f"解析失败: {exc}")
        return base


def _read_mp3_metadata(track: AudioTrack) -> AudioTrack:
    with track.path.open("rb") as handle:
        data = handle.read()

    title = ""
    artist = ""
    album = ""
    has_cover = False
    metadata_source = ""
    start_offset = 0

    if data[:3] == b"ID3" and len(data) >= 10:
        metadata_source = "ID3v2"
        version_major = data[3]
        tag_size = _synchsafe_to_int(data[6:10])
        start_offset = 10 + tag_size
        pos = 10
        tag_end = min(len(data), start_offset)
        while pos + 10 <= tag_end:
            frame_id = data[pos : pos + 4].decode("latin-1", errors="ignore").strip("\x00")
            frame_size = _decode_frame_size(data[pos + 4 : pos + 8], version_major)
            if not frame_id or frame_size <= 0:
                break
            frame_data_start = pos + 10
            frame_data_end = frame_data_start + frame_size
            if frame_data_end > tag_end:
                break
            frame_data = data[frame_data_start:frame_data_end]
            if frame_id in {"TIT2", "TPE1", "TALB"}:
                value = _decode_text_frame(frame_data)
                if frame_id == "TIT2" and value:
                    title = value
                elif frame_id == "TPE1" and value:
                    artist = value
                elif frame_id == "TALB" and value:
                    album = value
            elif frame_id == "APIC" and len(frame_data) > 4:
                has_cover = True
            pos = frame_data_end

    if (not title or not artist or not album) and len(data) >= 128 and data[-128:-125] == b"TAG":
        metadata_source = metadata_source or "ID3v1"
        title = title or _clean_id3v1_text(data[-125:-95])
        artist = artist or _clean_id3v1_text(data[-95:-65])
        album = album or _clean_id3v1_text(data[-65:-35])

    bitrate = _find_mp3_bitrate_kbps(data, start_offset)
    return replace(
        track,
        title=title,
        artist=artist,
        album=album,
        bitrate_kbps=bitrate,
        has_cover=has_cover,
        metadata_source=metadata_source,
    )


def _read_flac_metadata(track: AudioTrack) -> AudioTrack:
    with track.path.open("rb") as handle:
        if handle.read(4) != b"fLaC":
            return track

        title = ""
        artist = ""
        album = ""
        has_cover = False
        duration_seconds = None

        is_last = False
        while not is_last:
            header = handle.read(4)
            if len(header) < 4:
                break
            is_last = bool(header[0] & 0x80)
            block_type = header[0] & 0x7F
            block_length = int.from_bytes(header[1:4], "big")
            payload = handle.read(block_length)
            if len(payload) < block_length:
                break

            if block_type == 0 and len(payload) >= 34:
                packed = int.from_bytes(payload[10:18], "big")
                sample_rate = (packed >> 44) & 0xFFFFF
                total_samples = packed & 0xFFFFFFFFF
                if sample_rate and total_samples:
                    duration_seconds = total_samples / sample_rate
            elif block_type == 4 and len(payload) >= 8:
                comments = _parse_flac_vorbis_comment(payload)
                title = comments.get("title", title)
                artist = comments.get("artist", artist)
                album = comments.get("album", album)
            elif block_type == 6:
                has_cover = True

        bitrate = None
        if duration_seconds and duration_seconds > 0:
            bitrate = round((track.size_bytes * 8) / duration_seconds / 1000)

        return replace(
            track,
            title=title,
            artist=artist,
            album=album,
            duration_seconds=duration_seconds,
            bitrate_kbps=bitrate,
            has_cover=has_cover,
            metadata_source="FLAC",
        )


def _synchsafe_to_int(raw: bytes) -> int:
    return ((raw[0] & 0x7F) << 21) | ((raw[1] & 0x7F) << 14) | ((raw[2] & 0x7F) << 7) | (raw[3] & 0x7F)


def _decode_frame_size(raw: bytes, version_major: int) -> int:
    if version_major == 4:
        return _synchsafe_to_int(raw)
    return int.from_bytes(raw, "big")


def _decode_text_frame(frame_data: bytes) -> str:
    if not frame_data:
        return ""
    encoding = frame_data[0]
    raw_text = frame_data[1:]
    codec = {
        0: "latin-1",
        1: "utf-16",
        2: "utf-16-be",
        3: "utf-8",
    }.get(encoding, "latin-1")
    return raw_text.decode(codec, errors="ignore").strip("\x00").strip()


def _clean_id3v1_text(raw: bytes) -> str:
    return raw.decode("latin-1", errors="ignore").strip("\x00 ").strip()


def _find_mp3_bitrate_kbps(data: bytes, start_offset: int) -> int | None:
    limit = min(len(data) - 4, start_offset + 256_000)
    pos = start_offset
    while pos < limit:
        b1 = data[pos]
        b2 = data[pos + 1]
        if b1 == 0xFF and (b2 & 0xE0) == 0xE0:
            version_bits = (b2 >> 3) & 0x03
            layer_bits = (b2 >> 1) & 0x03
            if layer_bits != 0x01:
                pos += 1
                continue
            if version_bits == 0x03:
                version = "MPEG1"
            elif version_bits in {0x02, 0x00}:
                version = "MPEG2"
            else:
                pos += 1
                continue
            bitrate_index = (data[pos + 2] >> 4) & 0x0F
            bitrate = _BITRATE_TABLE.get((version, "Layer3"), [0] * 16)[bitrate_index]
            if bitrate:
                return bitrate
        pos += 1
    return None


def _parse_flac_vorbis_comment(payload: bytes) -> dict[str, str]:
    comments: dict[str, str] = {}
    pos = 0
    if len(payload) < 8:
        return comments
    vendor_length = struct.unpack_from("<I", payload, pos)[0]
    pos += 4 + vendor_length
    if pos + 4 > len(payload):
        return comments
    comment_count = struct.unpack_from("<I", payload, pos)[0]
    pos += 4
    for _ in range(comment_count):
        if pos + 4 > len(payload):
            break
        length = struct.unpack_from("<I", payload, pos)[0]
        pos += 4
        if pos + length > len(payload):
            break
        entry = payload[pos : pos + length].decode("utf-8", errors="ignore")
        pos += length
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        lowered = key.strip().lower()
        if lowered in {"title", "artist", "album"} and value.strip():
            comments[lowered] = value.strip()
    return comments
