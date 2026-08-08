"""Saying why the app didn't start, on a machine with nowhere to print it.

The PC's taskbar shortcut runs pythonw.exe, which has no console: a startup
failure there produces nothing at all — no window, no message, no trace, just
an app that never appears. The Mac shell at least puts up "the engine keeps
exiting". This is the PC's version of that, and it says which piece is missing
rather than only that something is."""
import io

from highdeas.startup import describe_failure, dialog_for, report


def test_a_missing_dependency_names_it_and_how_to_install_it():
    # The failure that has taken this app down twice: the virtualenv is missing
    # something app.py imports, so the app dies before any of its own code runs.
    error = ModuleNotFoundError("No module named 'dotenv'", name="dotenv")

    message = describe_failure(error, python=r"C:\repo\.venv\Scripts\python.exe",
                               repo=r"C:\repo")

    assert "dotenv" in message
    assert r"C:\repo\.venv\Scripts\python.exe -m pip install -e C:\repo" in message


def test_any_other_failure_still_says_what_went_wrong():
    # Whatever else can go wrong on the way up -- a port already taken, a
    # malformed .env -- reads the same way from the taskbar: nothing happened.
    # A message naming the exception beats no message at all, and pip is not the
    # answer to it, so don't offer pip.
    error = OSError("address already in use")

    message = describe_failure(error, python="python", repo="/repo")

    assert "address already in use" in message
    assert "pip install" not in message


def test_the_reason_goes_to_the_console_and_to_a_dialog():
    # Both, because neither is always there: under pythonw the stream goes
    # nowhere and only the dialog lands, while the Mac shell captures the stream
    # and has no dialog to show.
    shown = []
    stream = io.StringIO()

    report("it broke", dialog=shown.append, stream=stream)

    assert shown == ["it broke"]
    assert "it broke" in stream.getvalue()


def test_only_windows_gets_a_dialog():
    # ctypes.windll exists nowhere else, so asking for it on the Mac would fail
    # inside the failure reporter -- losing the reason it was called to give.
    assert dialog_for("darwin") is None
    assert dialog_for("win32") is not None
