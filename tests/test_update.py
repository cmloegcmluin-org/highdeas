"""The updater: notice when main has moved past the running app, and swap it in.

Both desks run from git checkouts of a fast-moving main; a stale app reads as
sync bugs (a store full of changes its pages don't know how to show). The
checker fetches sparingly, reports how far behind the checkout is, and — on
request — fast-forwards and relaunches the process."""
from types import SimpleNamespace

import pytest

from highdeas.update import UpdateChecker


class FakeGit:
    """Records git invocations and scripts their outcomes."""

    def __init__(self, behind="0", fetch_fails=False, pull_fails=False):
        self.calls = []
        self._behind = behind
        self._fetch_fails = fetch_fails
        self._pull_fails = pull_fails

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        sub = cmd[3]  # ["git", "-C", <repo>, <subcommand>, ...]
        if sub == "fetch":
            return SimpleNamespace(returncode=1 if self._fetch_fails else 0, stdout="", stderr="")
        if sub == "rev-list":
            return SimpleNamespace(returncode=0, stdout=self._behind + "\n", stderr="")
        if sub == "pull":
            return SimpleNamespace(returncode=1 if self._pull_fails else 0,
                                   stdout="", stderr="cannot fast-forward" if self._pull_fails else "")
        raise AssertionError(f"unexpected git call: {cmd}")

    def of(self, sub):
        return [c for c in self.calls if c[3] == sub]


def _checker(git, *, gap=600, now=None):
    clock = now or (lambda: 1000.0)
    return UpdateChecker("/repo", runner=git, min_fetch_gap=gap, clock=clock)


def test_status_reports_how_far_behind_origin_main_the_checkout_is(tmp_path):
    git = FakeGit(behind="3")

    checker = _checker(git)

    assert checker.status() == {"behind": 3}
    assert git.of("fetch") and git.of("rev-list")


def test_fetches_are_throttled_but_the_count_stays_fresh(tmp_path):
    # The page asks often; origin should not be hammered. Between fetches the
    # local rev-list still answers (a pull done by hand shows up immediately).
    ticks = iter([1000.0, 1001.0, 1002.0])
    git = FakeGit(behind="1")
    checker = _checker(git, gap=600, now=lambda: next(ticks))

    checker.status()
    checker.status()
    checker.status()

    assert len(git.of("fetch")) == 1
    assert len(git.of("rev-list")) == 3


def test_an_unreachable_origin_reads_as_up_to_date(tmp_path):
    # Offline must never nag: no network, no popup.
    git = FakeGit(behind="9", fetch_fails=True)

    assert _checker(git).status() == {"behind": 0}


def test_update_pulls_fast_forward_only_and_relaunches(tmp_path):
    git = FakeGit(behind="2")
    spawned = []

    checker = UpdateChecker("/repo", runner=git, respawn=lambda: spawned.append(True))
    checker.update()

    (pull,) = git.of("pull")
    assert "--ff-only" in pull
    assert spawned == [True]


def test_a_diverged_checkout_refuses_to_update_and_does_not_relaunch(tmp_path):
    git = FakeGit(pull_fails=True)
    spawned = []
    checker = UpdateChecker("/repo", runner=git, respawn=lambda: spawned.append(True))

    with pytest.raises(RuntimeError):
        checker.update()

    assert spawned == []


# --- becoming current at launch ----------------------------------------------


class FakeChecker:
    def __init__(self, behind=0, refuse=False):
        self._behind = behind
        self._refuse = refuse
        self.pulled = 0
        self.respawned = 0

    def status(self):
        return {"behind": self._behind}

    def pull(self):
        if self._refuse:
            raise RuntimeError("cannot fast-forward")
        self.pulled += 1

    def respawn(self):
        self.respawned += 1


def test_launch_becomes_current_when_behind():
    from highdeas.app import _become_current
    checker = FakeChecker(behind=3)

    _become_current(checker)

    assert checker.pulled == 1
    assert checker.respawned == 1


def test_launch_proceeds_untouched_when_current():
    from highdeas.app import _become_current
    checker = FakeChecker(behind=0)

    _become_current(checker)

    assert checker.pulled == 0
    assert checker.respawned == 0


def test_a_diverged_checkout_launches_what_it_has():
    from highdeas.app import _become_current
    checker = FakeChecker(behind=2, refuse=True)

    _become_current(checker)  # must not raise, must not respawn

    assert checker.respawned == 0
