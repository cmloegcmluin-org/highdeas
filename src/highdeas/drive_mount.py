"""Starting Google Drive for Desktop when a memo needs it and it isn't running.

DriveMusicRouter refuses to file a memo whose Drive base folder isn't there, because
creating it would put the audio on a local disk nothing ever uploads from and report
the send as done (see routers.DriveMusicRouter.route). That refusal stays. But on a
machine where Drive *is* installed and signed in, much the commonest reason the folder
is missing is the dullest one: Drive for Desktop simply isn't running.

That is what happened on the PC on 2026-08-10. It had last booted the day before at
12:51; Google's own updater replaced the app two minutes later at 12:53, and Drive
never started at all -- no mount, no G: drive, and no log line for the whole day. Every
music memo was refused until it was started by hand, and nothing about the refusal
could be fixed from inside Highdeas, even though the fix was one process launch.

So the router gets one attempt at that launch before it gives up: start Drive the way
this machine's own login item already does, wait a bounded few seconds for the mount,
and then let the folder check speak for itself. Nothing in here creates the folder, and
wake() reports nothing about how it went -- the caller re-reads the folder afterwards,
so the folder, never this module's opinion, is what decides whether a memo may be filed.
"""
import subprocess
import sys
import time
from pathlib import Path

# How long a submit will wait for the mount after starting Drive, and how often it
# looks. Drive took about ten seconds to mount from cold on Douglas's PC, so this
# leaves room for a slower start without turning his click into an unbounded hang --
# and the wait is only ever paid on a submit that was already about to be refused.
WAIT_SECONDS = 20
POLL_SECONDS = 0.5

_RUN_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "GoogleDriveFS"


def _login_item():
    """The command Windows itself starts Drive for Desktop with at login, or "" when
    there is no such entry. Read from the registry rather than spelled out here: Drive's
    installer keeps this value pointing at the version actually installed and rewrites
    it on every update, so a hardcoded path would go stale on exactly the event that
    tends to leave Drive not running in the first place."""
    try:
        import winreg
    except ImportError:  # not Windows -- launch_command only asks here when it is
        return ""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY)
    except OSError:
        return ""
    try:
        value, _kind = winreg.QueryValueEx(key, _RUN_VALUE)
    except OSError:  # Drive installed without its login item, or never installed
        return ""
    finally:
        winreg.CloseKey(key)
    return value


def launch_command(platform=None, *, login_item=_login_item):
    """What starts Drive for Desktop on this machine, or "" when there is nothing here
    to start. An argv list on macOS, where `open -a` finds the app bundle wherever it
    was installed; the login item's own command string on Windows. subprocess.Popen
    takes either shape, so callers don't have to know which one they got."""
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return ["open", "-a", "Google Drive"]
    return login_item()


def start(platform=None, *, command=launch_command, spawn=subprocess.Popen):
    """Start Drive for Desktop. True when something was actually launched, False when
    there was nothing to launch or launching it failed -- a machine with no Drive at
    all, or a login item naming a version since deleted. Never raises: this runs inside
    one of Douglas's submits, which must end in the refusal it was already heading for
    rather than a traceback."""
    argv = command(platform)
    if not argv:
        return False
    try:
        spawn(argv)
    except OSError:
        return False
    return True


def wake(base, *, start=start, sleep=time.sleep, monotonic=time.monotonic):
    """Best-effort: start Drive for Desktop and wait a bounded few seconds for `base`
    to turn up. Returns nothing at all, deliberately -- see the module docstring."""
    base = Path(base)
    if base.is_dir():
        return
    if not start():
        return
    deadline = monotonic() + WAIT_SECONDS
    while not base.is_dir() and monotonic() < deadline:
        sleep(POLL_SECONDS)
