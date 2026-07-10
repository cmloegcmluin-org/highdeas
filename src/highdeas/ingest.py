"""Discover new voice-memo recordings, ask iCloud for the ones it is still holding
in the cloud, and read when each was recorded."""
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".caf", ".aiff"}

# Windows file attributes. The first three mark a file the sync engine is holding in
# the cloud: its name is on this PC, its bytes are not. The last two are the pin state
# Explorer's "Always keep on this device" / "Free up space" write.
_OFFLINE = 0x0000_1000
_RECALL_ON_OPEN = 0x0004_0000
_RECALL_ON_DATA_ACCESS = 0x0040_0000
_CLOUD_ONLY = _OFFLINE | _RECALL_ON_OPEN | _RECALL_ON_DATA_ACCESS
_PINNED = 0x0008_0000
_UNPINNED = 0x0010_0000

_MP4_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)

# The 12-hex-digit fingerprint recording_key appends, so an already-keyed name is
# recognised as one and handed straight back rather than keyed a second time.
_KEY_SUFFIX = re.compile(r"-[0-9a-f]{12}$")


@dataclass(frozen=True)
class NewRecording:
    """A freshly-arrived recording: the raw file as it currently sits in the
    inbox, and the content-unique `name` (see recording_key) it should be stored
    and renamed to."""
    source: Path
    name: str


def _file_attributes(path):
    """The Windows attribute bits of `path`; 0 where a platform has none."""
    return getattr(Path(path).stat(), "st_file_attributes", 0)


def is_cloud_placeholder(path, *, attributes_of=_file_attributes):
    """True when the recording's name is on this PC but its bytes are still in iCloud.

    Reading the attributes never pulls a file down; opening one does."""
    return bool(attributes_of(path) & _CLOUD_ONLY)


def request_local_copy(path):
    """Ask iCloud to bring a recording it is holding in the cloud down to this PC.

    Highdeas must never be the one to pull a recording down. Reading a cloud-only
    file makes Windows recall it on the caller's behalf, and Windows announces every
    such recall with its "Automatic file downloads" toast — titled after python, the
    process that asked. Pinning the file is what Explorer's "Always keep on this
    device" writes: the download becomes iCloud's to do, and a later scan finds the
    recording whole, on this PC, and silent."""
    try:
        import ctypes

        attributes = _file_attributes(path)
        ctypes.windll.kernel32.SetFileAttributesW(
            str(path), (attributes | _PINNED) & ~_UNPINNED,
        )
    except Exception:  # noqa: BLE001 — not Windows, or the sync engine refused; scan on
        pass


def find_new_recordings(inbox_dir, known_names, *, still_in_cloud=is_cloud_placeholder,
                        request_download=request_local_copy):
    """Inbox recordings not yet in the store, each paired with its content key.

    A recording is new when its recording_key isn't already among `known_names`.
    Keying by content rather than by the raw filename is what rescues a recycled
    inbox name — voice-8.m4a reused for a new recording once the inbox has been
    cleared — from being mistaken for the earlier memo that used that name.

    A recording iCloud hasn't finished bringing down has no content to key, so it is
    left shut and asked for instead; the scan that runs once it lands picks it up."""
    inbox = Path(inbox_dir)
    if not inbox.is_dir():
        return []
    found = []
    for entry in sorted(inbox.iterdir(), key=lambda p: p.name):
        if not (entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS):
            continue
        if still_in_cloud(entry):
            request_download(entry)
            continue
        name = recording_key(entry)
        if name not in known_names:
            found.append(NewRecording(entry, name))
    return found


def recording_key(path, name=None):
    """The filename a recording is stored under, unique to the recording itself.

    The iOS Shortcut recycles inbox names — every new recording lands as
    voice-8.m4a once the inbox has been cleared — so a name alone can't tell a
    fresh recording apart from one already processed or deleted. Folding a
    fingerprint of the file's size and embedded recording time into the name
    gives every distinct recording its own stable key: unique in the store and
    on disk, in both the inbox and the bin.

    Only Highdeas writes a key into a name, so a name that already carries one is
    taken at its word: re-keying is idempotent, and — since opening a file is what
    pulls it down from iCloud — an adopted recording is never read again to be named.

    `name` keys the content of `path` as if it were stored under that filename:
    an upload sits staged under a temp name ingest ignores, but must land under
    the key of the filename the client intended."""
    path = Path(path)
    named = Path(name) if name else path
    if _KEY_SUFFIX.search(named.stem):
        return named.name
    fingerprint = f"{path.stat().st_size}:{recording_time(path)}"
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
    return f"{named.stem}-{digest}{named.suffix}"


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
