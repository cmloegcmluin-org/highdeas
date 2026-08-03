"""Notice when main has moved past the running app, and swap the new code in.

Both desks run Highdeas from git checkouts of one fast-moving main. A stale
app reads as a sync bug — the shared store fills with changes its pages don't
know how to show — so the app itself watches origin and offers a one-click
"pull and relaunch". Loopback pages only; nothing network-facing can reach it.
"""
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

# Keep git from flashing a console window on Windows — the checker runs every
# few minutes from a windowless (pythonw) process. A no-op (0) elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# The file that says what the app needs installed. A pull that moves it is a pull
# whose code wants something this machine's virtualenv may not have yet.
MANIFEST = "pyproject.toml"


def relaunch_command(executable=None, argv=None):
    """How to start this app again, faithful to how it was started.

    A module run (`python -m highdeas.app`) shows app.py's file path as
    argv[0]; replaying that as a loose script would lose the package context,
    so it becomes `-m` again. Anything else — the PC's `pythonw
    run_highdeas.py` taskbar launcher above all — is replayed verbatim: that
    script is what puts src on the path, and a child that skips it dies on
    its first import with no console to say why."""
    executable = executable or sys.executable
    argv = argv if argv is not None else sys.argv
    if argv and argv[0].endswith("app.py"):
        return [executable, "-m", "highdeas.app", *argv[1:]]
    return [executable, *argv]


def respawn_environment(environ, dotenv_keys):
    """The child's environment: everything inherited except what .env put
    there. load_dotenv never overrides an existing variable, so a .env value
    that rides the respawn shadows any fresh edit to the file — an updated
    API key would silently stay old until a cold start. Launcher-owned
    variables (PYTHONPATH, the Mac shell's port) ride on untouched."""
    dropped = set(dotenv_keys)
    return {key: value for key, value in environ.items() if key not in dropped}


def close_inherited_descriptors():
    """Mark every descriptor above the standard streams close-on-exec.

    The relaunch is an exec, which keeps the process — and with it every
    descriptor not marked to close. Werkzeug marks its listening socket
    *inheritable* (its reloader hands the bound socket to the child), so the
    freshly-exec'd app inherits the very ports it exists to serve, fails to bind
    them, and exits at startup complaining the address is in use — about itself.
    The app is then simply gone: on the Mac, a window on a splash screen with no
    engine under it.

    Standard streams are left alone: they are how a failed relaunch says
    anything at all. No-op where fcntl doesn't exist — Windows respawns through
    Popen(close_fds=True), which already covers this.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover — Windows takes the Popen path
        return
    for name in os.listdir("/dev/fd") if os.path.isdir("/dev/fd") else ():
        try:
            descriptor = int(name)
        except ValueError:
            continue
        if descriptor <= 2:
            continue
        try:
            flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
            fcntl.fcntl(descriptor, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
        except OSError:
            continue  # the listing itself opened one that is already gone


def _relaunch(repo=None):
    """Become the freshly-pulled code. On Windows, exec is spawn-and-exit
    with rough edges (thread contexts, window sessions) — do the spawn
    explicitly and leave; elsewhere, a true exec keeps the pid, which the
    Mac shell relies on to keep tracking its engine child."""
    command = relaunch_command()
    environment = dict(os.environ)
    if repo is not None:
        try:
            from dotenv import dotenv_values

            environment = respawn_environment(
                os.environ, dotenv_values(Path(repo) / ".env").keys())
        except Exception:  # noqa: BLE001 — a broken .env must not block the update
            pass
    if sys.platform == "win32":
        subprocess.Popen(command, close_fds=True, env=environment)
        os._exit(0)
    close_inherited_descriptors()
    os.execve(command[0], command, environment)


class UpdateChecker:
    """Thread-tolerant: status() is called from request threads; the git
    subprocesses are already serialized by their own cheapness and the fetch
    throttle, and a raced double-fetch is merely wasteful."""

    def __init__(self, repo_root, *, runner=subprocess.run, min_fetch_gap=600,
                 clock=time.monotonic, respawn=None, executable=None):
        self._repo = str(repo_root)
        self._run = runner
        self._min_fetch_gap = min_fetch_gap
        self._clock = clock
        self._respawn = respawn
        self._executable = executable or sys.executable
        self._last_fetch = None

    def _git(self, *args):
        return self._run(["git", "-C", self._repo, *args],
                         capture_output=True, text=True, creationflags=_NO_WINDOW)

    def status(self):
        """How far behind origin/main this checkout is, as {'behind': N}.

        Fetches at most every min_fetch_gap seconds — the page asks often and
        origin shouldn't be hammered — but counts against the local ref every
        time, so a pull done by hand shows up immediately. Trouble reaching
        origin reads as up to date: an offline machine must never nag."""
        now = self._clock()
        if self._last_fetch is None or now - self._last_fetch >= self._min_fetch_gap:
            self._last_fetch = now
            if self._git("fetch", "--quiet", "origin", "main").returncode != 0:
                return {"behind": 0}
        counted = self._git("rev-list", "--count", "HEAD..origin/main")
        if counted.returncode != 0:
            return {"behind": 0}
        try:
            return {"behind": int(counted.stdout.strip())}
        except ValueError:
            return {"behind": 0}

    def pull(self):
        """Fast-forward to origin/main, and install anything the new code needs.

        --ff-only so a checkout that has somehow diverged refuses loudly instead
        of merging by surprise; the caller turns the refusal into a notice.

        The install belongs here rather than at the call sites: both desks pull
        by themselves and neither runs pip afterwards, so a release that adds a
        package would otherwise land as an app quietly missing it — on the
        machine nobody is sitting at, for as long as it takes to notice."""
        pulled = self._git("pull", "--ff-only", "origin", "main")
        if pulled.returncode != 0:
            raise RuntimeError(pulled.stderr.strip() or "git pull refused")
        self.ensure_dependencies()

    def ensure_dependencies(self):
        """Install into this virtualenv whatever the manifest now asks for, unless
        it is already what was last installed from.

        The question deliberately is not "did this pull move the manifest". That
        asks about one pull, and answers it once: an install that failed — offline
        at the wrong moment, a package that wouldn't build — was never tried
        again, and the app went on launching against a virtualenv missing what its
        code imports. That is how the MacBook lost Highdeas for days; a pull
        introduced google-auth, its install didn't take, and every launch after
        that died on the import while the checkout sat perfectly up to date. Asking
        instead whether the virtualenv matches the manifest keeps asking until an
        install succeeds, and catches a pull done by hand into the bargain."""
        wanted = self._manifest_digest()
        if wanted is None or wanted == self._installed_digest():
            return
        print("Highdeas: installing what the new code needs.")
        done = self._run(
            [self._executable, "-m", "pip", "install", "-e", self._repo, "--quiet"],
            capture_output=True, text=True, creationflags=_NO_WINDOW)
        if done.returncode != 0:
            # A failure is only a printed line: offline, or a package that won't
            # build, must still leave the app launching on the code it already has,
            # with whatever wants the missing package failing where it is used.
            # Nothing is recorded, so the next launch tries again.
            print(f"Highdeas: couldn't install them ({done.stderr.strip()}); "
                  "launching on what this machine already has.")
            return
        self._remember_installed(wanted)

    def _manifest_digest(self):
        """What the code wants installed, as a fingerprint — or None where there is
        no manifest to read, which is not a machine to install on."""
        try:
            return hashlib.sha256((Path(self._repo) / MANIFEST).read_bytes()).hexdigest()
        except OSError:
            return None

    def _installed_record(self):
        """Where this virtualenv remembers the manifest it was last installed from.

        Inside the virtualenv, because that is what the record is about — a second
        virtualenv on the same checkout has its own answer — and because the
        virtualenv is already ignored by git and never synced between machines."""
        return Path(self._executable).parent.parent / ".highdeas-installed"

    def _installed_digest(self):
        try:
            return self._installed_record().read_text().strip()
        except OSError:
            return None

    def _remember_installed(self, digest):
        """Best effort: an unwritable virtualenv costs a pip run per launch, which
        is slow but correct — never a launch that fails."""
        try:
            self._installed_record().write_text(digest)
        except OSError:
            pass

    def respawn(self):
        """Replace this process with a fresh launch of the pulled code."""
        if self._respawn is not None:
            self._respawn()
        else:
            _relaunch(self._repo)

    def update(self):
        """Pull and relaunch in one stroke. Callers answering an HTTP request
        respond between the two instead (see web.update)."""
        self.pull()
        self.respawn()
