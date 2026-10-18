"""The MP4 container the phone records into."""
from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)


def creation_time(path):
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
        made = (_EPOCH + timedelta(seconds=seconds)).astimezone()
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
