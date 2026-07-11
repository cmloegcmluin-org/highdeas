import io
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from highdeas.app import (
    _ingest_continuously,
    _open_when_ready,
    _open_window,
    _run_browser,
    _start_upload_listener,
    build_app,
    platform_defaults,
    build_upload_app,
    default_bin_dir,
)
from highdeas.store import Memo, MemoStore
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
    fake_window.maximize()
    fake_window.close()

    assert load_geometry(path).maximized is True


def test_ingest_continuously_keeps_rescanning_the_inbox_off_the_calling_thread():
    stop, done, threads = threading.Event(), threading.Event(), []

    class FakeService:
        def refresh(self):
            threads.append(threading.get_ident())
            if len(threads) == 2:
                stop.set()
                done.set()

    _ingest_continuously(FakeService(), interval=0, stop=stop)

    assert done.wait(timeout=2)
    assert threads[0] != threading.get_ident()  # off the UI thread, so the window opens now
    # It scans on and on, so a memo recorded while the bin is the page on screen still
    # reaches the inbox: ingestion belongs to the app, not to whichever view is open.
    assert len(threads) == 2


def test_ingest_continuously_keeps_scanning_after_a_failing_refresh():
    stop, done, calls = threading.Event(), threading.Event(), []

    class BadService:
        def refresh(self):
            calls.append(1)
            if len(calls) == 2:
                stop.set()
                done.set()
            raise RuntimeError("boom")

    # A bad recording must never crash startup, nor end the scan that follows it.
    _ingest_continuously(BadService(), interval=0, stop=stop)

    assert done.wait(timeout=2)


def test_chrome_launcher_opens_the_url_in_the_configured_profile(monkeypatch):
    import highdeas.app as app_mod
    calls = []
    monkeypatch.setattr(app_mod.subprocess, "Popen", lambda args: calls.append(args))
    monkeypatch.setenv("HIGHDEAS_CHROME_EXE", r"C:\chrome.exe")
    monkeypatch.setenv("HIGHDEAS_CHROME_PROFILE", "Default")

    app_mod._chrome_launcher()("https://drive.google.com/x")

    # A link can't choose a Chrome profile, so the app launches Chrome pinned to it.
    assert calls == [[r"C:\chrome.exe", "--profile-directory=Default", "https://drive.google.com/x"]]


def test_default_bin_dir_sits_beside_the_inbox(tmp_path):
    # The bin must live in the same parent folder as the inbox, so retiring a
    # recording (inbox -> bin) moves it *within* the same iCloud tree. Moving a
    # file out of the iCloud folder makes iCloud Drive on Windows pop a per-file
    # "move off iCloud" confirmation dialog for every Submit/Trash.
    inbox = tmp_path / "Highdeas"

    result = Path(default_bin_dir(str(inbox)))

    assert result == tmp_path / "Highdeas Bin"
    assert result.parent == inbox.parent


def test_build_app_reads_every_folder_from_the_environment(tmp_path, monkeypatch):
    inbox, bin_dir, drive = tmp_path / "inbox", tmp_path / "bin", tmp_path / "drive"
    inbox.mkdir()
    db_path = tmp_path / "memos.db"
    monkeypatch.setenv("HIGHDEAS_INBOX_DIR", str(inbox))
    monkeypatch.setenv("HIGHDEAS_BIN_DIR", str(bin_dir))
    monkeypatch.setenv("HIGHDEAS_DB", str(db_path))
    monkeypatch.setenv("HIGHDEAS_DRIVE_BASE", str(drive))
    (inbox / "voice-3.m4a").write_bytes(b"AUDIO")

    app, _ = build_app()
    MemoStore(db_path).upsert(Memo(audio_filename="voice-3.m4a", route="drive"))
    response = app.test_client().post(
        "/submit/voice-3.m4a", data={"name": "Korok", "transcript": "", "route": "drive"}
    )

    # Submitting a Drive memo walks all four configured folders at once: it reads the
    # audio from the inbox, files a copy under the Drive base, retires the original to
    # the bin, and marks the row processed in the database the test seeded.
    assert response.status_code == 204
    today = datetime.now().strftime("%Y_%m_%d")
    assert (drive / f"_{today}_NOT_YET_PROCESSED_MUSIC" / "Korok.m4a").read_bytes() == b"AUDIO"
    assert (bin_dir / "voice-3.m4a").read_bytes() == b"AUDIO"
    assert not (inbox / "voice-3.m4a").exists()
    assert MemoStore(db_path).get("voice-3.m4a").status == "processed"


class FakeUploadService:
    """The two things the upload app asks of the inbox service."""

    def __init__(self, knows=False):
        self._knows = knows
        self.refreshed = threading.Event()
        self.waited = None

    def knows(self, audio_filename):
        return self._knows

    def refresh(self, wait=False):
        self.waited = wait
        self.refreshed.set()


def test_build_upload_app_is_off_until_a_token_is_configured(monkeypatch):
    # Without a shared token there is nothing safe to expose to the LAN.
    monkeypatch.delenv("HIGHDEAS_UPLOAD_TOKEN", raising=False)

    assert build_upload_app(FakeUploadService()) is None


def test_build_upload_app_accepts_a_recording_and_kicks_off_ingest(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setenv("HIGHDEAS_INBOX_DIR", str(inbox))
    monkeypatch.setenv("HIGHDEAS_UPLOAD_TOKEN", "tok")
    service = FakeUploadService()

    app = build_upload_app(service)
    response = app.test_client().post(
        "/upload",
        data={"audio": (io.BytesIO(b"RIFFxxxxWAVE"), "take.wav")},
        headers={"Authorization": "Bearer tok"},
    )

    assert response.status_code == 201
    assert (inbox / response.get_json()["stored"]).read_bytes() == b"RIFFxxxxWAVE"
    # Adoption doesn't wait for an open inbox page's poll: the upload triggers
    # a refresh itself — off the request thread, so the 2xx isn't held hostage
    # to transcription. And it must be a *waiting* refresh: during a burst the
    # in-flight scan predates this file, and a skipped trigger never recurs.
    assert service.refreshed.wait(timeout=2)
    assert service.waited is True


def test_build_upload_app_confirms_an_already_processed_recording_without_reingesting(
        tmp_path, monkeypatch):
    monkeypatch.setenv("HIGHDEAS_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("HIGHDEAS_UPLOAD_TOKEN", "tok")
    service = FakeUploadService(knows=True)

    app = build_upload_app(service)
    response = app.test_client().post(
        "/upload",
        data={"audio": (io.BytesIO(b"RIFFxxxxWAVE"), "take.wav")},
        headers={"Authorization": "Bearer tok"},
    )

    assert response.status_code == 200
    assert not service.refreshed.is_set()


def test_start_upload_listener_serves_the_upload_app_to_the_lan(monkeypatch):
    monkeypatch.setenv("HIGHDEAS_UPLOAD_PORT", "5155")
    served = threading.Event()
    bound = {}

    class FakeApp:
        def run(self, host, port, threaded, use_reloader):
            bound.update(host=host, port=port)
            served.set()

    _start_upload_listener(FakeApp())

    # Off the calling thread (both UI modes block their own thread on their own
    # server), reachable from the LAN, on the configured port.
    assert served.wait(timeout=2)
    assert bound == {"host": "0.0.0.0", "port": 5155}


def test_start_upload_listener_stays_dark_without_an_upload_app():
    _start_upload_listener(None)  # no token configured: nothing must listen


def test_a_malformed_upload_port_disables_the_listener_not_the_app(monkeypatch, capsys):
    # Every other env misconfiguration in this app degrades gracefully; a
    # typo'd port must not take the window down with it (invisibly, under
    # the pythonw taskbar launch).
    monkeypatch.setenv("HIGHDEAS_UPLOAD_PORT", "5,055")
    ran = []

    class FakeApp:
        def run(self, **kwargs):
            ran.append(kwargs)

    _start_upload_listener(FakeApp())

    assert ran == []
    assert "HIGHDEAS_UPLOAD_PORT" in capsys.readouterr().out


def test_a_failed_bind_reports_itself_instead_of_dying_silently(monkeypatch, capsys):
    # A second Highdeas instance (or another app on the port) would otherwise
    # leave the window working and the phone retrying forever with no clue.
    monkeypatch.setenv("HIGHDEAS_UPLOAD_PORT", "5155")
    failed = threading.Event()

    class FakeApp:
        def run(self, **kwargs):
            try:
                raise OSError("Address already in use")
            finally:
                failed.set()

    _start_upload_listener(FakeApp())

    assert failed.wait(timeout=2)
    deadline = time.monotonic() + 2
    out = ""
    while "upload listener" not in out and time.monotonic() < deadline:
        out += capsys.readouterr().out
        time.sleep(0.02)
    assert "upload listener" in out


def test_main_starts_the_upload_listener_before_the_blocking_ui(monkeypatch):
    import highdeas.app as app_mod
    order = []
    monkeypatch.setenv("HIGHDEAS_DESKTOP", "0")
    monkeypatch.setattr(app_mod, "_set_windows_app_id", lambda: None)
    monkeypatch.setattr(app_mod, "build_app", lambda: ("APP", "SERVICE"))
    monkeypatch.setattr(app_mod, "_ingest_continuously", lambda service: None)
    monkeypatch.setattr(app_mod, "build_upload_app", lambda service: ("UPLOAD-FOR", service))
    monkeypatch.setattr(app_mod, "_start_upload_listener",
                        lambda app: order.append(("upload", app)))
    monkeypatch.setattr(app_mod, "_run_browser", lambda app: order.append(("ui", app)))

    app_mod.main()

    # _run_browser (and the desktop path) block for the process lifetime, so
    # the listener must be up first — "after the UI" would mean never.
    assert order == [("upload", ("UPLOAD-FOR", "SERVICE")), ("ui", "APP")]


def test_run_browser_serves_on_the_configured_port_without_opening_a_browser(monkeypatch):
    monkeypatch.setenv("HIGHDEAS_PORT", "5123")
    monkeypatch.setenv("HIGHDEAS_OPEN_BROWSER", "0")
    served = []

    class FakeApp:
        def run(self, port):
            served.append(port)

    _run_browser(FakeApp())

    # Browser-mode fallback: the port is honoured, and nothing pops a tab open.
    assert served == [5123]


def test_main_falls_back_to_the_browser_when_the_desktop_window_is_switched_off(monkeypatch):
    import highdeas.app as app_mod
    opened = []
    monkeypatch.setenv("HIGHDEAS_DESKTOP", "0")
    monkeypatch.delenv("HIGHDEAS_UPLOAD_TOKEN", raising=False)
    monkeypatch.setattr(app_mod, "_set_windows_app_id", lambda: None)
    monkeypatch.setattr(app_mod, "build_app", lambda: ("APP", "SERVICE"))
    monkeypatch.setattr(app_mod, "_ingest_continuously", lambda service: None)
    monkeypatch.setattr(app_mod, "_run_desktop", lambda app: opened.append(("desktop", app)) or True)
    monkeypatch.setattr(app_mod, "_run_browser", lambda app: opened.append(("browser", app)))

    app_mod.main()

    # The documented escape hatch: HIGHDEAS_DESKTOP=0 must never reach the native window,
    # even though _run_desktop would have succeeded had it been asked.
    assert opened == [("browser", "APP")]


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


def test_platform_defaults_windows_keeps_the_original_paths():
    defaults = platform_defaults("win32")

    assert defaults.inbox == r"C:\Users\Douglas\iCloudDrive\iCloud~is~workflow~my~workflows\Highdeas"
    assert defaults.chrome == r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    assert defaults.drive_base == r"G:\My Drive\voice memos (top level)"


def test_platform_defaults_mac_points_at_mac_realities(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    defaults = platform_defaults("darwin")

    # The Shortcut's iCloud container as macOS mounts it, and Chrome's binary
    # inside its app bundle. Drive's mount varies per account; .env carries
    # the real value — the default just has to be somewhere sane under HOME.
    assert defaults.inbox == str(
        tmp_path / "Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/Highdeas")
    assert defaults.chrome == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert defaults.drive_base.startswith(str(tmp_path))


def test_build_app_and_upload_app_read_defaults_through_the_platform(monkeypatch, tmp_path):
    # Whatever the platform, the env always wins — pin that the refactor kept
    # the environment override path intact end to end.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv("HIGHDEAS_INBOX_DIR", str(inbox))
    monkeypatch.setenv("HIGHDEAS_UPLOAD_TOKEN", "tok")

    app = build_upload_app(FakeUploadService())
    response = app.test_client().post(
        "/upload",
        data={"audio": (io.BytesIO(b"RIFFxxxxWAVE"), "take.wav")},
        headers={"Authorization": "Bearer tok"},
    )

    assert response.status_code == 201
    assert list(inbox.iterdir())
