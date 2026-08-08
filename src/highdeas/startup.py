"""Say why the app didn't start, on a machine with nowhere to print it.

Standard library only, and deliberately so: this is what runs when the
virtualenv is missing something, so it must not need anything from it.
"""
import sys


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
        # MB_OK | MB_ICONERROR | MB_SETFOREGROUND, so it comes up in front of
        # whatever the reader was doing rather than behind it.
        ctypes.windll.user32.MessageBoxW(None, message, "Highdeas", 0x10 | 0x10000)

    return show


def report(message, *, dialog=None, stream=None):
    """Put the reason wherever this machine can show it.

    Both paths, because neither is always available: under pythonw the stream
    goes nowhere and only the dialog lands; the Mac shell captures the stream
    and has no dialog. A dialog that itself fails must not replace the failure
    being reported with its own."""
    print(message, file=stream if stream is not None else sys.stderr, flush=True)
    if dialog is not None:
        try:
            dialog(message)
        except Exception:  # noqa: BLE001 — the message already went to the stream
            pass


def describe_failure(error, *, python, repo):
    """A startup failure, as something to read and something to do about it.

    A missing import is the one failure with a known cure, so it gets the
    command that cures it. Everything else gets named rather than guessed at:
    an install is not the answer to a taken port, and offering it would send
    the reader somewhere the problem isn't."""
    if isinstance(error, ModuleNotFoundError) and error.name:
        return (f"Highdeas couldn't start: this virtualenv is missing "
                f"{error.name}.\n\nInstall what it needs:\n\n"
                f"{python} -m pip install -e {repo}")
    return (f"Highdeas couldn't start.\n\n"
            f"{type(error).__name__}: {error}")
