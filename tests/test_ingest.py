import os
import struct
from datetime import datetime

from highdeas.ingest import (
    NewRecording,
    find_new_recordings,
    is_cloud_placeholder,
    recording_key,
    recording_time,
    request_local_copy,
)

# The Windows attribute bit that says a file's bytes are still only in the cloud, and
# the two that carry its pin state ("Always keep on this device" / "Free up space").
_RECALL_ON_DATA_ACCESS = 0x0040_0000
_PINNED = 0x0008_0000
_UNPINNED = 0x0010_0000

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


def test_find_new_asks_icloud_for_a_recording_it_has_not_downloaded_yet(tmp_path):
    # Reading a cloud-only recording makes Windows recall it on Highdeas' behalf and
    # announce that with a toast named after python, the process that asked. Leave the
    # file shut, ask iCloud to bring it down, and key it on a later scan.
    waiting = tmp_path / "voice-9.m4a"
    waiting.write_bytes(_mp4(1_700_000_000))
    asked = []

    result = find_new_recordings(
        tmp_path,
        known_names=set(),
        still_in_cloud=lambda path: True,
        request_download=asked.append,
    )

    assert result == []
    assert [path.name for path in asked] == ["voice-9.m4a"]


def test_find_new_never_asks_for_a_recording_whose_bytes_are_already_here(tmp_path):
    landed = tmp_path / "voice.m4a"
    landed.write_bytes(_mp4(1_700_000_000))
    asked = []

    result = find_new_recordings(tmp_path, known_names=set(), request_download=asked.append)

    # Nothing to download, so nothing is asked of iCloud — and the recording is ingested.
    assert [r.source.name for r in result] == ["voice.m4a"]
    assert asked == []


def test_is_cloud_placeholder_reads_the_attribute_windows_marks_a_dataless_file_with(tmp_path):
    recording = tmp_path / "v.m4a"
    recording.write_bytes(_mp4(1_700_000_000))

    assert is_cloud_placeholder(recording) is False  # written here, so its bytes are here
    assert is_cloud_placeholder(recording, attributes_of=lambda _: _RECALL_ON_DATA_ACCESS) is True


def test_request_local_copy_pins_the_recording_so_icloud_downloads_it(tmp_path, monkeypatch):
    import ctypes

    recording = tmp_path / "v.m4a"
    recording.write_bytes(b"AUDIO")
    calls = []

    class FakeKernel32:
        def SetFileAttributesW(self, path, attributes):
            calls.append((path, attributes))
            return 1

    class FakeWinDLL:
        kernel32 = FakeKernel32()

    monkeypatch.setattr(ctypes, "windll", FakeWinDLL(), raising=False)

    request_local_copy(recording)

    # Pinning is what Explorer's "Always keep on this device" sets: it hands the
    # download to iCloud instead of Highdeas triggering it by opening the file.
    (path, attributes), = calls
    assert path == str(recording)
    assert attributes & _PINNED
    assert not attributes & _UNPINNED


def test_request_local_copy_is_a_no_op_where_windows_file_attributes_do_not_exist(tmp_path, monkeypatch):
    import ctypes

    recording = tmp_path / "v.m4a"
    recording.write_bytes(b"AUDIO")
    monkeypatch.delattr(ctypes, "windll", raising=False)

    request_local_copy(recording)  # nothing to pin, and nothing to crash the scan


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


def test_recording_key_can_key_a_staged_file_under_its_intended_name(tmp_path):
    # An upload is staged under a temp name ingest ignores (.part); its key must
    # be built from the filename the client intended, not the staging name.
    staged = tmp_path / "upload-1234.part"
    staged.write_bytes(_mp4(1_700_000_000))

    key = recording_key(staged, name="voice-8.m4a")

    landed = tmp_path / "voice-8.m4a"
    staged.rename(landed)
    assert key == recording_key(landed)


def test_recording_key_names_an_already_keyed_recording_without_reading_it(tmp_path):
    raw = tmp_path / "voice-8.m4a"
    raw.write_bytes(_mp4(1_700_000_000))
    key = recording_key(raw)

    keyed = tmp_path / key
    raw.rename(keyed)

    # Re-keying the already-renamed file must not stack a second fingerprint...
    assert recording_key(keyed) == key
    # ...and it takes the name at its word rather than re-reading the recording, which
    # on iCloud is what pulls a file down. Nothing here exists to be read.
    assert recording_key(tmp_path / "gone-abcdef123456.m4a") == "gone-abcdef123456.m4a"
