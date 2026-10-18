"""Builders for MP4/M4A recordings: minimal byte blobs with a real `moov/mvhd`
creation time — the container fact ingest keys recordings by — and real sound made
by ffmpeg, laid out the way the phone leaves a recording it never got to stop."""
import struct
import subprocess

from highdeas.audio import NO_WINDOW, locate_ffmpeg

# Seconds between the MP4 epoch (1904-01-01 UTC) and the Unix epoch (1970-01-01 UTC).
MP4_TO_UNIX = 2082844800

# Where the phone's recorder starts writing sound, after the room it keeps for the
# index it writes only when it is stopped.
PHONE_SOUND_STARTS = 61440


def box(box_type, payload):
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def mvhd(creation_seconds, *, version=0):
    head = bytes([version, 0, 0, 0])  # version + 3 flag bytes
    if version == 1:
        stamp = struct.pack(">Q", creation_seconds) + b"\x00" * 20
    else:
        stamp = struct.pack(">I", creation_seconds) + b"\x00" * 12
    return box(b"mvhd", head + stamp)


def mp4(unix_seconds, *, version=0, moov_first=True, sound=b"\x00" * 16):
    ftyp = box(b"ftyp", b"isom")
    moov = box(b"moov", mvhd(unix_seconds + MP4_TO_UNIX, version=version))
    mdat = box(b"mdat", sound)
    return ftyp + moov + mdat if moov_first else ftyp + mdat + moov


def tone(path, *, seconds):
    """A real recording: a steady tone, encoded the way the phone encodes speech."""
    subprocess.run([locate_ffmpeg(), "-y", "-hide_banner", "-f", "lavfi",
                    "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
                    "-ac", "1", "-c:a", "aac", "-b:a", "96k", "-f", "ipod", str(path)],
                   check=True, capture_output=True, creationflags=NO_WINDOW)
    return path


def left_unstopped(finished):
    """A finished recording's bytes as they stood before it was stopped: its file type,
    the room left for an index never written, then its sound."""
    ftyp = _top_level(finished, b"ftyp")
    sound = _top_level(finished, b"mdat")[8:]
    return ftyp + bytes(PHONE_SOUND_STARTS - len(ftyp)) + sound


def _top_level(data, box_type):
    at = 0
    while at < len(data):
        size = int.from_bytes(data[at:at + 4], "big")
        if data[at + 4:at + 8] == box_type:
            return data[at:at + size]
        at += size
    raise KeyError(box_type)
