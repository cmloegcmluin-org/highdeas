"""Discover new voice-memo recordings and read when each was recorded."""
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".caf", ".aiff"}

_MP4_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)

# The 12-hex-digit fingerprint recording_key appends, so re-keying an
# already-keyed file strips the old suffix instead of stacking a second one.
_KEY_SUFFIX = re.compile(r"-[0-9a-f]{12}$")


@dataclass(frozen=True)
class NewRecording:
    """A freshly-arrived recording: the raw file as it currently sits in the
    inbox, and the content-unique `name` (see recording_key) it should be stored
    and renamed to."""
    source: Path
    name: str


def find_new_recordings(inbox_dir, known_names):
    """Inbox recordings not yet in the store, each paired with its content key.

    A recording is new when its recording_key isn't already among `known_names`.
    Keying by content rather than by the raw filename is what rescues a recycled
    inbox name — voice-8.m4a reused for a new recording once the inbox has been
    cleared — from being mistaken for the earlier memo that used that name."""
    inbox = Path(inbox_dir)
    if not inbox.is_dir():
        return []
    found = []
    for entry in sorted(inbox.iterdir(), key=lambda p: p.name):
        if entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS:
            name = recording_key(entry)
            if name not in known_names:
                found.append(NewRecording(entry, name))
    return found


def recording_key(path):
    """The filename a recording is stored under, unique to the recording itself.

    The iOS Shortcut recycles inbox names — every new recording lands as
    voice-8.m4a once the inbox has been cleared — so a name alone can't tell a
    fresh recording apart from one already processed or deleted. Folding a
    fingerprint of the file's size and embedded recording time into the name
    gives every distinct recording its own stable key: unique in the store and
    on disk, in both the inbox and the bin. Re-keying an already-keyed file
    yields the same name, so ingest stays idempotent."""
    path = Path(path)
    fingerprint = f"{path.stat().st_size}:{recording_time(path)}"
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    stem = _KEY_SUFFIX.sub("", path.stem)
    return f"{stem}-{digest}{path.suffix}"


def recording_time(path):
    """Local ISO timestamp of when `path` was recorded.

    iOS stamps the true recording moment into the MP4/M4A container, so prefer
    that; fall back to the file's modified time for other formats or when the
    container carries no usable timestamp."""
    made = _mp4_creation_time(path) or datetime.fromtimestamp(Path(path).stat().st_mtime)
    return made.isoformat(timespec="seconds")


def _mp4_creation_time(path):
    """The `moov/mvhd` creation time of an MP4/M4A file as naive local time, or
    None if the file isn't MP4 or doesn't carry a real timestamp."""
    try:
        with open(path, "rb") as file:
            file.seek(0, 2)
            end = file.tell()
            file.seek(0)
            moov = _find_box(file, b"moov", end)
            if moov is None:
                return None
            moov_start, moov_size = moov
            file.seek(moov_start)
            mvhd = _find_box(file, b"mvhd", moov_start + moov_size)
            if mvhd is None:
                return None
            file.seek(mvhd[0])
            version = file.read(4)[0]  # version byte, then 3 flag bytes
            seconds = int.from_bytes(file.read(8 if version == 1 else 4), "big")
    except (OSError, IndexError):
        return None
    if not seconds:
        return None
    try:
        made = (_MP4_EPOCH + timedelta(seconds=seconds)).astimezone()
    except (OverflowError, OSError, ValueError):
        return None
    return made.replace(tzinfo=None) if made.year >= 1980 else None


def _find_box(file, wanted, end):
    """Scan sibling MP4 boxes from the current offset up to `end`; return the
    (payload_offset, payload_size) of the first `wanted` box, or None."""
    while file.tell() < end:
        start = file.tell()
        header = file.read(8)
        if len(header) < 8:
            return None
        size = int.from_bytes(header[:4], "big")
        if size == 1:  # 64-bit extended size follows the header
            size = int.from_bytes(file.read(8), "big")
            header_len = 16
        elif size == 0:  # box runs to the end of its parent
            size = end - start
            header_len = 8
        else:
            header_len = 8
        if size < header_len:  # corrupt: would not advance
            return None
        if header[4:8] == wanted:
            return start + header_len, size - header_len
        file.seek(start + size)
    return None
