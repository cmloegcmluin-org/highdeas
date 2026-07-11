"""Notice when main has moved past the running app, and swap the new code in.

Both desks run Highdeas from git checkouts of one fast-moving main. A stale
app reads as a sync bug — the shared store fills with changes its pages don't
know how to show — so the app itself watches origin and offers a one-click
"pull and relaunch". Loopback pages only; nothing network-facing can reach it.
"""
import os
import subprocess
import sys
import time

# Keep git from flashing a console window on Windows — the checker runs every
# few minutes from a windowless (pythonw) process. A no-op (0) elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def _relaunch():
    """Become the freshly-pulled code. On Windows, exec is spawn-and-exit
    with rough edges (thread contexts, window sessions) — do the spawn
    explicitly and leave; elsewhere, a true exec keeps the pid, which the
    Mac shell relies on to keep tracking its engine child."""
    command = relaunch_command()
    if sys.platform == "win32":
        subprocess.Popen(command, close_fds=True)
        os._exit(0)
    os.execv(command[0], command)


class UpdateChecker:
    """Thread-tolerant: status() is called from request threads; the git
    subprocesses are already serialized by their own cheapness and the fetch
    throttle, and a raced double-fetch is merely wasteful."""

    def __init__(self, repo_root, *, runner=subprocess.run, min_fetch_gap=600,
                 clock=time.monotonic, respawn=_relaunch):
        self._repo = str(repo_root)
        self._run = runner
        self._min_fetch_gap = min_fetch_gap
        self._clock = clock
        self._respawn = respawn
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
        """Fast-forward to origin/main. --ff-only so a checkout that has
        somehow diverged refuses loudly instead of merging by surprise; the
        caller turns the refusal into a notice."""
        pulled = self._git("pull", "--ff-only", "origin", "main")
        if pulled.returncode != 0:
            raise RuntimeError(pulled.stderr.strip() or "git pull refused")

    def respawn(self):
        """Replace this process with a fresh launch of the pulled code."""
        self._respawn()

    def update(self):
        """Pull and relaunch in one stroke. Callers answering an HTTP request
        respond between the two instead (see web.update)."""
        self.pull()
        self.respawn()
