"""Read and join recordings with ffmpeg.

A group of notes plays one recording made of its members', end to end. Joining them —
and measuring them, so each member's word timings can be slid to where they land in the
joined file — is all this module does.
"""
import re
import subprocess
import tempfile
from pathlib import Path

# Keep ffmpeg from flashing a console window on Windows; a no-op (0) elsewhere.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ffmpeg dumps "Duration: 00:00:04.27, start: …" for every input it opens.
_DURATION = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


class AudioError(Exception):
    """Raised when ffmpeg cannot read or join a recording."""


def locate_ffmpeg():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd, runner):
    return runner(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)


def duration(src, *, ffmpeg_exe=None, runner=subprocess.run, locate=locate_ffmpeg):
    """How many seconds `src` runs for, read off ffmpeg's own header dump."""
    ffmpeg_exe = ffmpeg_exe or locate()
    result = _run([ffmpeg_exe, "-hide_banner", "-i", str(src), "-f", "null", "-"], runner)
    found = _DURATION.search(result.stderr or "")
    if not found:
        raise AudioError(f"ffmpeg could not read the length of {Path(src).name}")
    hours, minutes, seconds = found.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def join(sources, dest, *, ffmpeg_exe=None, runner=subprocess.run, locate=locate_ffmpeg):
    """Write `sources`, end to end and in order, to `dest`.

    Every recording comes off the same phone through the same Shortcut, so they share a
    codec and their streams are copied straight through. A stray one that doesn't is
    re-encoded rather than refused: a group whose audio had to be rebuilt is worth more
    than a group that couldn't be made."""
    ffmpeg_exe = ffmpeg_exe or locate()
    sources = [Path(source) for source in sources]
    if not sources:
        raise AudioError("nothing to join")
    with tempfile.TemporaryDirectory() as tmp:
        # ffmpeg's concat demuxer reads its inputs from a file, one quoted path per line.
        listing = Path(tmp) / "sources.txt"
        listing.write_text(
            "".join(f"file '{_quote(source)}'\n" for source in sources), encoding="utf-8"
        )
        opened = [ffmpeg_exe, "-y", "-hide_banner", "-f", "concat", "-safe", "0",
                  "-i", str(listing)]
        result = _run(opened + ["-c", "copy", str(dest)], runner)
        if result.returncode != 0:
            result = _run(opened + [str(dest)], runner)
        if result.returncode != 0:
            raise AudioError(
                f"ffmpeg could not join {len(sources)} recordings: {result.stderr}"
            )
    return Path(dest)


def cut(source, dest, start, end, *, ffmpeg_exe=None, runner=subprocess.run,
        locate=locate_ffmpeg):
    """Write `source` to `dest` with the seconds from `start` to `end` taken out.

    The samples either side are restamped so the two halves meet: without that they
    keep the times they were recorded at, and the removed stretch plays back as a
    silence exactly as long as what was cut. Restamping means re-encoding, which the
    join path already falls back to, so a cut recording is no stranger than a group's."""
    ffmpeg_exe = ffmpeg_exe or locate()
    keep = f"aselect='not(between(t,{round(start, 3)},{round(end, 3)}))',asetpts=N/SR/TB"
    result = _run([ffmpeg_exe, "-y", "-hide_banner", "-i", str(source),
                   "-af", keep, str(dest)], runner)
    if result.returncode != 0:
        raise AudioError(f"ffmpeg could not cut {Path(source).name}: {result.stderr}")
    return Path(dest)


def _quote(source):
    return str(source.resolve()).replace("'", r"'\''")
