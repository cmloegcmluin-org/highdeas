"""Saying why the app didn't start, on a machine with nowhere to print it.

The PC's taskbar shortcut runs pythonw.exe, which has no console: a startup
failure there produces nothing at all — no window, no message, no trace, just
an app that never appears. The Mac shell at least puts up "the engine keeps
exiting". This is the PC's version of that, and it says which piece is missing
rather than only that something is."""
import io
import sys
from types import SimpleNamespace

from highdeas.startup import describe_failure, dialog_for, report


def test_a_missing_dependency_names_it_and_how_to_install_it():
    # The failure that has taken this app down twice: the virtualenv is missing
    # something app.py imports, so the app dies before any of its own code runs.
    error = ModuleNotFoundError("No module named 'dotenv'", name="dotenv")

    message = describe_failure(error, python=r"C:\repo\.venv\Scripts\python.exe",
                               repo=r"C:\repo")

    assert "dotenv" in message
    assert r"C:\repo\.venv\Scripts\python.exe -m pip install -e C:\repo" in message


def test_the_install_command_is_one_that_shows_its_work():
    # The dialog only exists because the shortcut runs pythonw.exe -- and
    # sys.executable is therefore pythonw.exe, so a command built from it would
    # install with no console and no output. The reader would watch nothing
    # happen and conclude the fix hadn't worked. Hand them the console twin.
    error = ModuleNotFoundError("No module named 'flask'", name="flask")

    message = describe_failure(error, python=r"C:\repo\.venv\Scripts\pythonw.exe",
                               repo=r"C:\repo")

    assert r"C:\repo\.venv\Scripts\python.exe -m pip install -e C:\repo" in message
    assert "pythonw.exe" not in message


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


def test_the_windows_box_is_an_error_that_comes_to_the_front(monkeypatch):
    # The one step that cannot be exercised anywhere but Windows is the box
    # actually appearing, so pin down everything up to it: which call, and the
    # flags. MB_ICONERROR marks it as a failure rather than a notice, and
    # MB_SETFOREGROUND puts it in front of whatever the reader was doing --
    # without it the app that never appeared is joined by a dialog that never
    # appeared either, behind the window they were looking at.
    calls = []
    monkeypatch.setitem(sys.modules, "ctypes", SimpleNamespace(
        windll=SimpleNamespace(user32=SimpleNamespace(
            MessageBoxW=lambda *args: calls.append(args)))))

    dialog_for("win32")("it broke")

    MB_ICONERROR, MB_SETFOREGROUND = 0x10, 0x10000
    assert calls == [(None, "it broke", "Highdeas", MB_ICONERROR | MB_SETFOREGROUND)]
