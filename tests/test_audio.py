from types import SimpleNamespace

import pytest

from highdeas.audio import AudioError, duration, join


def _runner(returncode=0, stderr=""):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stderr=stderr, stdout="")

    run.calls = calls
    return run


def test_duration_reads_the_length_ffmpeg_reports(tmp_path):
    runner = _runner(stderr="  Duration: 00:01:04.27, start: 0.000000, bitrate: 64 kb/s\n")

    assert duration(tmp_path / "a.m4a", ffmpeg_exe="ff", runner=runner) == pytest.approx(64.27)
    assert runner.calls[0][0] == "ff"


def test_duration_raises_when_ffmpeg_says_nothing_about_the_length(tmp_path):
    runner = _runner(returncode=1, stderr="No such file or directory")

    with pytest.raises(AudioError):
        duration(tmp_path / "gone.m4a", ffmpeg_exe="ff", runner=runner)


def test_join_copies_the_streams_through_and_names_every_source(tmp_path):
    runner = _runner()

    join([tmp_path / "a.m4a", tmp_path / "b.m4a"], tmp_path / "out.m4a",
         ffmpeg_exe="ff", runner=runner)

    # One pass, streams copied: the recordings share a codec, so nothing is re-encoded.
    assert len(runner.calls) == 1
    assert "-c" in runner.calls[0] and "copy" in runner.calls[0]
    assert runner.calls[0][-1].endswith("out.m4a")


def test_join_re_encodes_when_the_streams_will_not_copy(tmp_path):
    # A recording in some other codec must not cost the user the group.
    attempts = []

    def run(cmd, **kwargs):
        attempts.append(cmd)
        failed = "copy" in cmd
        return SimpleNamespace(returncode=1 if failed else 0, stderr="codec mismatch", stdout="")

    join([tmp_path / "a.m4a", tmp_path / "b.wav"], tmp_path / "out.m4a",
         ffmpeg_exe="ff", runner=run)

    assert len(attempts) == 2
    assert "copy" in attempts[0] and "copy" not in attempts[1]


def test_join_raises_when_even_re_encoding_fails(tmp_path):
    runner = _runner(returncode=1, stderr="Invalid data found")

    with pytest.raises(AudioError):
        join([tmp_path / "a.m4a"], tmp_path / "out.m4a", ffmpeg_exe="ff", runner=runner)
