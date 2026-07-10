"""Builders for minimal MP4/M4A byte blobs with a real `moov/mvhd` creation
time — the container fact ingest keys recordings by. Shared by the ingest and
upload tests."""
import struct

# Seconds between the MP4 epoch (1904-01-01 UTC) and the Unix epoch (1970-01-01 UTC).
MP4_TO_UNIX = 2082844800


def box(box_type, payload):
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def mvhd(creation_seconds, *, version=0):
    head = bytes([version, 0, 0, 0])  # version + 3 flag bytes
    if version == 1:
        stamp = struct.pack(">Q", creation_seconds) + b"\x00" * 20
    else:
        stamp = struct.pack(">I", creation_seconds) + b"\x00" * 12
    return box(b"mvhd", head + stamp)


def mp4(unix_seconds, *, version=0, moov_first=True):
    ftyp = box(b"ftyp", b"isom")
    moov = box(b"moov", mvhd(unix_seconds + MP4_TO_UNIX, version=version))
    mdat = box(b"mdat", b"\x00" * 16)
    return ftyp + moov + mdat if moov_first else ftyp + mdat + moov
