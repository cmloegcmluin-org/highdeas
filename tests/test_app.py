import threading
from pathlib import Path
from types import SimpleNamespace

from highdeas.app import (
    _open_when_ready,
    _open_window,
    _transcribe_in_background,
    default_bin_dir,
)
from highdeas.window_state import WindowGeometry, load_geometry, save_geometry


def test_open_when_ready_shows_the_app_only_after_the_server_is_serving():
    events = []

    class FakeWindow:
        def load_url(self, url):
            events.append(("load", url))

    _open_when_ready(FakeWindow(), "http://127.0.0.1:9/", lambda: events.append(("waited",)))

    # Wait for the server, then swap the splash for the real page — the open never
    # blocks on warming the model or transcribing the backlog.
    assert events == [("waited",), ("load", "http://127.0.0.1:9/")]


def _fake_webview(fake_window, screens=()):
    calls = []

    def create_window(title, **kwargs):
        calls.append((title, kwargs))
        return fake_window

    return SimpleNamespace(screens=list(screens), create_window=create_window), calls


def test_open_window_reopens_at_the_geometry_the_window_was_last_closed_at(tmp_path, fake_window):
    path = tmp_path / "window.json"
    save_geometry(path, WindowGeometry(width=800, height=600, x=10, y=20, maximized=False))
    webview, calls = _fake_webview(fake_window, [SimpleNamespace(x=0, y=0, width=1920, height=1080)])

    _open_window(webview, path)

    (title, kwargs), = calls
    assert title == "Highdeas"
    assert (kwargs["width"], kwargs["height"]) == (800, 600)
    assert (kwargs["x"], kwargs["y"]) == (10, 20)
    assert kwargs["maximized"] is False


def test_open_window_opens_maximized_before_anything_has_been_remembered(tmp_path, fake_window):
    webview, calls = _fake_webview(fake_window)

    _open_window(webview, tmp_path / "window.json")

    (_, kwargs), = calls
    assert kwargs["maximized"] is True


def test_open_window_forgets_a_position_no_connected_monitor_covers(tmp_path, fake_window):
    # The monitor the window was closed on is gone; opening there would put it out of reach.
    path = tmp_path / "window.json"
    save_geometry(path, WindowGeometry(x=-1900, y=0, maximized=False))
    webview, calls = _fake_webview(fake_window, [SimpleNamespace(x=0, y=0, width=1920, height=1080)])

    _open_window(webview, path)

    (_, kwargs), = calls
    assert (kwargs["x"], kwargs["y"]) == (None, None)
    # ...and the stranded position is not written back when the window closes.
    fake_window.events.closing.fire()
    assert (load_geometry(path).x, load_geometry(path).y) == (None, None)


def test_open_window_tracks_the_window_so_the_next_launch_reopens_maximized(tmp_path, fake_window):
    path = tmp_path / "window.json"
    save_geometry(path, WindowGeometry(maximized=False))
    webview, _ = _fake_webview(fake_window)

    _open_window(webview, path)
    fake_window.events.maximized.fire()
    fake_window.events.closing.fire()

    assert load_geometry(path).maximized is True


def test_transcribe_in_background_runs_refresh_off_the_calling_thread():
    ran = threading.Event()
    seen = {}

    class FakeService:
        def refresh(self):
            seen["thread"] = threading.get_ident()
            ran.set()

    _transcribe_in_background(FakeService())

    assert ran.wait(timeout=2)
    assert seen["thread"] != threading.get_ident()  # off the UI thread, so the window opens now


def test_transcribe_in_background_survives_a_failing_refresh():
    ran = threading.Event()

    class BadService:
        def refresh(self):
            ran.set()
            raise RuntimeError("boom")

    # A bad recording must never crash startup: the background thread swallows it.
    _transcribe_in_background(BadService())

    assert ran.wait(timeout=2)


def test_chrome_launcher_opens_the_url_in_the_configured_profile(monkeypatch):
    import highdeas.app as app_mod
    calls = []
    monkeypatch.setattr(app_mod.subprocess, "Popen", lambda args: calls.append(args))
    monkeypatch.setenv("VOICE_CHROME_EXE", r"C:\chrome.exe")
    monkeypatch.setenv("VOICE_CHROME_PROFILE", "Default")

    app_mod._chrome_launcher()("https://drive.google.com/x")

    # A link can't choose a Chrome profile, so the app launches Chrome pinned to it.
    assert calls == [[r"C:\chrome.exe", "--profile-directory=Default", "https://drive.google.com/x"]]


def test_default_bin_dir_sits_beside_the_inbox(tmp_path):
    # The bin must live in the same parent folder as the inbox, so retiring a
    # recording (inbox -> bin) moves it *within* the same iCloud tree. Moving a
    # file out of the iCloud folder makes iCloud Drive on Windows pop a per-file
    # "move off iCloud" confirmation dialog for every Submit/Trash.
    inbox = tmp_path / "VoiceInbox"

    result = Path(default_bin_dir(str(inbox)))

    assert result == tmp_path / "VoiceBin"
    assert result.parent == inbox.parent


def test_set_windows_app_id_uses_the_app_id_the_shortcut_carries(monkeypatch):
    import ctypes

    import highdeas.app as app_mod

    calls = []

    class FakeShell32:
        def SetCurrentProcessExplicitAppUserModelID(self, app_id):
            calls.append(app_id)

    class FakeWinDLL:
        shell32 = FakeShell32()

    monkeypatch.setattr(ctypes, "windll", FakeWinDLL(), raising=False)

    app_mod._set_windows_app_id()

    # Windows only merges the running window into the pinned Highdeas.lnk when this
    # process AUMID exactly equals the shortcut's System.AppUserModel.ID. Pin the two
    # values together here: if the app or Create-HighdeasShortcut.ps1 changes it, the
    # taskbar silently regresses to pythonw.exe's generic python icon.
    assert calls == ["Douglas.Highdeas"]
    assert app_mod.APP_ID == "Douglas.Highdeas"
