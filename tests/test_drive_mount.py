from pathlib import Path

from highdeas import drive_mount


class FakeClock:
    """A monotonic() that only ever moves when sleep() is called, so a test can
    exhaust drive_mount's whole wait without spending any of its own."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def monotonic(self):
        return self.now


def test_wake_returns_at_once_when_there_is_nothing_here_to_start(tmp_path):
    # No Drive for Desktop on this machine at all. Waiting for a mount that nothing
    # is bringing up would spend the whole timeout on a submit that is already going
    # to be refused, so the wait never begins.
    clock = FakeClock()

    drive_mount.wake(tmp_path / "nowhere", start=lambda: False,
                     sleep=clock.sleep, monotonic=clock.monotonic)

    assert clock.slept == []


def test_wake_stops_as_soon_as_the_drive_folder_turns_up(tmp_path):
    # Drive takes a few seconds to mount after it is started -- so the wait polls,
    # and ends on the mount rather than on the clock.
    base = tmp_path / "My Drive" / "voice memos (top level)"
    clock = FakeClock()

    def sleep(seconds):
        clock.sleep(seconds)
        if len(clock.slept) == 3:
            base.mkdir(parents=True)

    drive_mount.wake(base, start=lambda: True, sleep=sleep, monotonic=clock.monotonic)

    assert len(clock.slept) == 3


def test_wake_gives_up_when_the_folder_never_appears(tmp_path):
    # Drive is installed but cannot mount -- signed out, or broken. The wait has to
    # end by itself: this is running inside a click of his, not a background pass.
    base = tmp_path / "nowhere"
    clock = FakeClock()

    drive_mount.wake(base, start=lambda: True, sleep=clock.sleep,
                     monotonic=clock.monotonic)

    assert sum(clock.slept) >= drive_mount.WAIT_SECONDS
    # Never invented on the way past: creating it is exactly what DriveMusicRouter
    # refuses to do, and waking Drive must not do it by the back door either.
    assert not base.exists()


def test_launch_command_on_a_mac_opens_the_drive_app():
    assert drive_mount.launch_command("darwin") == ["open", "-a", "Google Drive"]


def test_launch_command_on_windows_is_the_login_item_windows_already_has():
    # Not a path of our own guessing: Drive's own installer keeps this Run entry
    # pointing at the version actually installed, and rewrites it on every update.
    entry = r'"C:\Program Files\Google\Drive File Stream\129.0.1.0\GoogleDriveFS.exe" --startup_mode'

    assert drive_mount.launch_command("win32", login_item=lambda: entry) == entry


def test_launch_command_is_empty_when_windows_has_no_login_item_for_drive():
    assert drive_mount.launch_command("win32", login_item=lambda: "") == ""


def test_start_reports_nothing_started_when_there_is_no_command():
    started = []

    assert drive_mount.start("win32", command=lambda _platform: "",
                             spawn=started.append) is False
    assert started == []


def test_start_reports_nothing_started_when_the_command_will_not_run():
    # A stale Run entry naming a version that has since been deleted, say. The
    # caller must hear "no" rather than a raised OSError out of a submit.
    def spawn(_command):
        raise OSError("nope")

    assert drive_mount.start("win32", command=lambda _platform: "drive.exe",
                             spawn=spawn) is False


def test_start_runs_the_command_this_machine_gave_us():
    started = []

    assert drive_mount.start("darwin", command=lambda _platform: ["open", "-a", "X"],
                             spawn=started.append) is True
    assert started == [["open", "-a", "X"]]


def test_wake_leaves_a_folder_that_is_already_there_alone(tmp_path):
    # wake is only ever called once route() has found the base missing, but it must
    # still hold: a base that exists ends the wait before the first sleep.
    base = tmp_path / "base"
    base.mkdir()
    clock = FakeClock()

    drive_mount.wake(base, start=lambda: True, sleep=clock.sleep,
                     monotonic=clock.monotonic)

    assert clock.slept == []


def test_the_real_wake_starts_nothing_when_the_folder_is_already_there(tmp_path):
    # Nothing injected, so the module's own defaults are what run here -- a rename
    # inside drive_mount would otherwise break only the app, never a test. Safe to
    # run anywhere precisely because an existing folder is answered before start()
    # is ever reached, so this cannot launch Drive on the machine running the suite.
    base = tmp_path / "base"
    base.mkdir()

    assert drive_mount.wake(base) is None


def test_wake_polls_faster_than_it_waits():
    # A single sleep as long as the whole wait would turn a mount that arrives in
    # two seconds into a twenty-second pause.
    assert 0 < drive_mount.POLL_SECONDS < drive_mount.WAIT_SECONDS


def test_login_item_reads_the_run_entry_drive_installs(monkeypatch):
    # The Windows-only registry read, with winreg itself faked: the point under test
    # is which key and value name are asked for, not that winreg works.
    asked = {}

    class FakeWinreg:
        HKEY_CURRENT_USER = "HKCU"

        @staticmethod
        def OpenKey(root, path):
            asked["key"] = (root, path)
            return "handle"

        @staticmethod
        def QueryValueEx(handle, name):
            asked["value"] = (handle, name)
            return (r'"C:\...\GoogleDriveFS.exe" --startup_mode', 1)

        @staticmethod
        def CloseKey(handle):
            asked["closed"] = handle

    monkeypatch.setitem(__import__("sys").modules, "winreg", FakeWinreg)

    assert drive_mount._login_item() == r'"C:\...\GoogleDriveFS.exe" --startup_mode'
    assert asked["key"] == ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run")
    assert asked["value"] == ("handle", "GoogleDriveFS")
    assert asked["closed"] == "handle"


def test_login_item_is_empty_when_there_is_no_such_entry(monkeypatch):
    class FakeWinreg:
        HKEY_CURRENT_USER = "HKCU"

        @staticmethod
        def OpenKey(root, path):
            return "handle"

        @staticmethod
        def QueryValueEx(handle, name):
            raise FileNotFoundError(name)

        @staticmethod
        def CloseKey(handle):
            pass

    monkeypatch.setitem(__import__("sys").modules, "winreg", FakeWinreg)

    assert drive_mount._login_item() == ""


def test_login_item_is_empty_where_there_is_no_winreg_at_all(monkeypatch):
    # launch_command only reaches this on win32, but importing a Windows-only module
    # must not be able to take a submit down anywhere.
    monkeypatch.setitem(__import__("sys").modules, "winreg", None)

    assert drive_mount._login_item() == ""


def test_paths_are_taken_as_given_not_only_as_Path(tmp_path):
    # app.py hands DriveMusicRouter a str from the environment; the router keeps a
    # Path. wake has to cope with either, since its own default caller passes the
    # router's Path and a test may pass a str.
    base = tmp_path / "base"
    base.mkdir()
    clock = FakeClock()

    drive_mount.wake(str(base), start=lambda: True, sleep=clock.sleep,
                     monotonic=clock.monotonic)

    assert clock.slept == []
    assert Path(str(base)).is_dir()
