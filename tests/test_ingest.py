import os
import struct
from datetime import datetime

from voicememo.ingest import NewRecording, find_new_recordings, recording_key, recording_time

# Seconds between the MP4 epoch (1904-01-01 UTC) and the Unix epoch (1970-01-01 UTC).
_MP4_TO_UNIX = 2082844800


def _box(box_type, payload):
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def _mvhd(creation_seconds, *, version=0):
    head = bytes([version, 0, 0, 0])  # version + 3 flag bytes
    if version == 1:
        stamp = struct.pack(">Q", creation_seconds) + b"\x00" * 20
    else:
        stamp = struct.pack(">I", creation_seconds) + b"\x00" * 12
    return _box(b"mvhd", head + stamp)


def _mp4(unix_seconds, *, version=0, moov_first=True):
    ftyp = _box(b"ftyp", b"isom")
    moov = _box(b"moov", _mvhd(unix_seconds + _MP4_TO_UNIX, version=version))
    mdat = _box(b"mdat", b"\x00" * 16)
    return ftyp + moov + mdat if moov_first else ftyp + mdat + moov


def _local_iso(unix_seconds):
    return datetime.fromtimestamp(unix_seconds).isoformat(timespec="seconds")


def test_find_new_returns_audio_keyed_by_content_excluding_known_and_non_audio(tmp_path):
    keep = tmp_path / "voice.m4a"
    keep.write_bytes(_mp4(1_700_000_000))
    skip = tmp_path / "voice-2.m4a"
    skip.write_bytes(_mp4(1_700_000_500))
    (tmp_path / "notes.txt").write_text("not audio")

    result = find_new_recordings(tmp_path, known_names={recording_key(skip)})

    # Each new recording is paired with the content key it should be stored under.
    assert [r.source.name for r in result] == ["voice.m4a"]
    assert [r.name for r in result] == [recording_key(keep)]


def test_find_new_ingests_a_recycled_inbox_name_whose_content_is_new(tmp_path):
    # The store still holds a retired memo under the raw name voice-8.m4a; the
    # Shortcut has now dropped a genuinely different recording under that name.
    arrival = tmp_path / "voice-8.m4a"
    arrival.write_bytes(_mp4(1_700_000_000))

    result = find_new_recordings(tmp_path, known_names={"voice-8.m4a"})

    # Matching by content key (not the raw name) rescues the new recording.
    assert [r.source.name for r in result] == ["voice-8.m4a"]
    assert result[0].name == recording_key(arrival) != "voice-8.m4a"


def test_missing_inbox_returns_empty(tmp_path):
    assert find_new_recordings(tmp_path / "does_not_exist", known_names=set()) == []


def test_recording_time_reads_the_embedded_recording_moment(tmp_path):
    recording = tmp_path / "v.m4a"
    recording.write_bytes(_mp4(1_783_456_624))

    assert recording_time(recording) == _local_iso(1_783_456_624)


def test_recording_time_reads_a_64bit_creation_time(tmp_path):
    recording = tmp_path / "v.m4a"
    recording.write_bytes(_mp4(1_783_456_624, version=1))

    assert recording_time(recording) == _local_iso(1_783_456_624)


def test_recording_time_finds_moov_at_the_end_of_the_file(tmp_path):
    recording = tmp_path / "v.m4a"
    recording.write_bytes(_mp4(1_783_456_624, moov_first=False))

    assert recording_time(recording) == _local_iso(1_783_456_624)


def test_recording_time_falls_back_to_mtime_for_a_non_mp4_file(tmp_path):
    recording = tmp_path / "v.wav"
    recording.write_bytes(b"RIFF....WAVEfmt  not really an mp4")
    os.utime(recording, (1_699_999_999, 1_699_999_999))

    assert recording_time(recording) == _local_iso(1_699_999_999)


def test_recording_time_falls_back_to_mtime_when_creation_time_is_zero(tmp_path):
    recording = tmp_path / "v.m4a"
    recording.write_bytes(_box(b"ftyp", b"isom") + _box(b"moov", _mvhd(0)))
    os.utime(recording, (1_700_000_000, 1_700_000_000))

    assert recording_time(recording) == _local_iso(1_700_000_000)


def test_recording_key_distinguishes_a_reused_name_with_new_content(tmp_path):
    # The Shortcut recycles inbox names: voice-8.m4a is reused for each new
    # recording once the inbox has been cleared. Same name, different recording.
    first = tmp_path / "voice-8.m4a"
    first.write_bytes(_mp4(1_700_000_000))
    first_key = recording_key(first)
    first.unlink()

    second = tmp_path / "voice-8.m4a"
    second.write_bytes(_mp4(1_700_009_999))

    assert recording_key(second) != first_key
    assert recording_key(second).endswith(".m4a")


def test_recording_key_is_idempotent_when_reapplied_to_a_keyed_file(tmp_path):
    raw = tmp_path / "voice-8.m4a"
    raw.write_bytes(_mp4(1_700_000_000))
    key = recording_key(raw)

    keyed = tmp_path / key
    raw.rename(keyed)

    # Re-keying the already-renamed file must not stack a second fingerprint.
    assert recording_key(keyed) == key
