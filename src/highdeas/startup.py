"""Say why the app didn't start, on a machine with nowhere to print it.

Standard library only, and deliberately so: this is what runs when the
virtualenv is missing something, so it must not need anything from it.
"""
import sys
import time

# A failure, not a notice; and in front of whatever the reader was doing rather
# than behind it — an app that never appeared should not be joined by a dialog
# that never appeared either.
MB_ICONERROR = 0x10
MB_SETFOREGROUND = 0x10000


def dialog_for(platform):
    """A way to put a message on screen, or None where there isn't one.

    Windows only, because Windows is where the need is: the taskbar shortcut
    runs pythonw.exe, which has no console, so a failure on the way up prints
    into nothing and the app simply never appears. user32 is always there —
    unlike anything the virtualenv might be missing."""
    if platform != "win32":
        return None
    import ctypes

    def show(message):
        ctypes.windll.user32.MessageBoxW(
            None, message, "Highdeas", MB_ICONERROR | MB_SETFOREGROUND)

    return show


def report(message, *, dialog=None, stream=None, record=None):
    """Put the reason wherever this machine can show it, and leave it on disk.

    Every route, because none of them is always there: under pythonw the stream
    goes nowhere and only the dialog lands; the Mac shell captures the stream
    and has no dialog. The record outlives both — a dialog is only read by
    someone sitting in front of it, and this app fails on the way up, when
    nobody necessarily is. Whoever is asked "why won't it open" later should
    find the answer waiting rather than reconstruct it.

    Neither a dialog nor a disk that refuses may replace the failure being
    reported with one of its own."""
    print(message, file=stream if stream is not None else sys.stderr, flush=True)
    if record is not None:
        try:
            record.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{message}\n")
        except OSError:
            pass
    if dialog is not None:
        try:
            dialog(message)
        except Exception:  # noqa: BLE001 — the message already went to the stream
            pass


def forget(record):
    """Drop a previous failure once the app has got past the point of failing.

    A stale reason is worse than none: it describes a machine that has since
    been fixed, and sends the next reader after a problem that isn't there."""
    try:
        record.unlink()
    except OSError:
        pass


def _with_a_console(python):
    """The console twin of the interpreter that is running.

    This dialog exists because the shortcut runs pythonw.exe, so that is what
    sys.executable holds — and a pip command built from it would install with
    no console and no output at all. The reader would run the fix, watch
    nothing happen, and reasonably conclude it hadn't worked."""
    if python.lower().endswith("pythonw.exe"):
        return python[:-len("pythonw.exe")] + "python.exe"
    return python


def describe_failure(error, *, python, repo):
    """A startup failure, as something to read and something to do about it.

    A missing import is the one failure with a known cure, so it gets the
    command that cures it. Everything else gets named rather than guessed at:
    an install is not the answer to a taken port, and offering it would send
    the reader somewhere the problem isn't."""
    if isinstance(error, ModuleNotFoundError) and error.name:
        return (f"Highdeas couldn't start: this virtualenv is missing "
                f"{error.name}.\n\nInstall what it needs:\n\n"
                f"{_with_a_console(python)} -m pip install -e {repo}")
    return (f"Highdeas couldn't start.\n\n"
            f"{type(error).__name__}: {error}")
