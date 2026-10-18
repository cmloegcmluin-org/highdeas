"""The MP4 container the phone records into."""
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)

# The phone's recorder (ios/Highdeas/Recorder.swift) writes AAC-LC, 48 kHz, one channel.
# It starts its sound at this offset, keeping the room before it for the index it writes
# only when it is stopped; a recording it never got to stop has zeros there instead.
_PHONE_SOUND_STARTS = 61440
_PHONE_RATE = 48_000
_PHONE_AUDIO_CONFIG = bytes([0x11, 0x88])  # AudioSpecificConfig: AAC-LC, 48 kHz, mono
_AAC_FRAME = 1024
_IDENTITY_MATRIX = struct.pack(">9I", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)


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


def never_finished(path):
    """Whether `path` is a recording the phone never got to stop: its file type, then
    only the empty room kept for an index, then sound."""
    try:
        with open(path, "rb") as file:
            head = file.read(_PHONE_SOUND_STARTS + 1)
    except OSError:
        return False
    if head[4:8] != b"ftyp" or len(head) <= _PHONE_SOUND_STARTS:
        return False
    return not any(head[int.from_bytes(head[:4], "big"):_PHONE_SOUND_STARTS])


def indexed_for_decoding(path):
    """`path`'s bytes behind the index its recorder never wrote, one that hands all of
    its sound to the decoder as a single piece. AAC frames carry no lengths of their
    own, and a decoder given several at once reads them one after another; the length
    the index declares is a placeholder that bounds nothing."""
    data = Path(path).read_bytes()
    ftyp = data[:int.from_bytes(data[:4], "big")]
    sound = data[_PHONE_SOUND_STARTS:]
    room = _box(b"free", bytes(_PHONE_SOUND_STARTS - len(ftyp) - 16))
    mdat = struct.pack(">I", 8 + len(sound)) + b"mdat"
    return ftyp + room + mdat + sound + _one_piece_moov(len(sound))


def _one_piece_moov(sound_size):
    times = struct.pack(">II", 0, 0)
    mvhd = _full_box(b"mvhd", times + struct.pack(">II", _PHONE_RATE, _AAC_FRAME)
                     + struct.pack(">IH", 0x10000, 0x100) + bytes(10) + _IDENTITY_MATRIX
                     + bytes(24) + struct.pack(">I", 2))
    tkhd = _full_box(b"tkhd", times + struct.pack(">III", 1, 0, _AAC_FRAME) + bytes(8)
                     + struct.pack(">HHHH", 0, 0, 0x100, 0) + _IDENTITY_MATRIX + bytes(8),
                     flags=3)
    mdhd = _full_box(b"mdhd", times + struct.pack(">IIHH", _PHONE_RATE, _AAC_FRAME, 0x55C4, 0))
    hdlr = _full_box(b"hdlr", bytes(4) + b"soun" + bytes(13))
    dinf = _box(b"dinf", _full_box(b"dref", struct.pack(">I", 1) + _full_box(b"url ", b"", flags=1)))
    stbl = _box(b"stbl", _phone_sample_description()
                + _full_box(b"stts", struct.pack(">III", 1, 1, _AAC_FRAME))
                + _full_box(b"stsc", struct.pack(">IIII", 1, 1, 1, 1))
                + _full_box(b"stsz", struct.pack(">III", 0, 1, sound_size))
                + _full_box(b"stco", struct.pack(">II", 1, _PHONE_SOUND_STARTS)))
    minf = _box(b"minf", _full_box(b"smhd", bytes(4)) + dinf + stbl)
    return _box(b"moov", mvhd + _box(b"trak", tkhd + _box(b"mdia", mdhd + hdlr + minf)))


def _phone_sample_description():
    decoder_config = _descriptor(0x04, bytes([0x40, 0x15]) + bytes(11)
                                 + _descriptor(0x05, _PHONE_AUDIO_CONFIG))
    stream = _descriptor(0x03, struct.pack(">HB", 1, 0) + decoder_config
                         + _descriptor(0x06, b"\x02"))
    mp4a = _box(b"mp4a", bytes(6) + struct.pack(">H", 1) + bytes(8)
                + struct.pack(">HHHHI", 1, 16, 0, 0, _PHONE_RATE << 16)
                + _full_box(b"esds", stream))
    return _full_box(b"stsd", struct.pack(">I", 1) + mp4a)


def _box(kind, payload):
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _full_box(kind, payload, *, flags=0):
    return _box(kind, struct.pack(">I", flags) + payload)


def _descriptor(tag, payload):
    return bytes([tag, len(payload)]) + payload


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
