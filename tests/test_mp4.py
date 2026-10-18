from audio_files import left_unstopped, mp4

from highdeas.mp4 import never_finished


def test_a_recording_the_phone_never_stopped_is_told_apart_from_a_stopped_one(tmp_path):
    stopped = tmp_path / "stopped.m4a"
    stopped.write_bytes(mp4(1_700_000_000, sound=b"the sound itself"))
    unstopped = tmp_path / "unstopped.m4a"
    unstopped.write_bytes(left_unstopped(stopped.read_bytes()))

    assert never_finished(unstopped)
    assert not never_finished(stopped)
