# Working on Highdeas

Two machines run this app from git checkouts of `main`: Douglas's Windows PC and
his MacBook. Both apps **self-update from origin/main** (pull at launch, pull-and-
relaunch when idle) — anything you land goes live on his desks within minutes.
Land accordingly: whole suite green, small single-purpose commits, no WIP.

**The phone is not one of them.** An iOS app cannot pull from git, so landing an
`ios/` change on `main` reaches the desks and leaves the phone exactly as it was.
It updates only by `ios/resign.sh` with the iPhone plugged in and *unlocked* — the
build is long enough that it auto-locks partway, so unlock it again for the install
step. Until that runs, a phone fix is not fixed, however green the suite is: say so
rather than reporting it landed. And if you need the phone, **ask for it** — Douglas
would rather plug it in than have you verify around its absence on a simulator.

## How work lands

- Work on a branch in a worktree (`git worktree add .claude/worktrees/<name> -b
  claude/<name>`), never in the primary checkout.
- `main` moves fast (parallel agents). Sync by `git rebase main` on a clean tree;
  never `reset` to tidy or to sync.
- Land: suite green → ff-merge your branch at the primary checkout → push origin.
- On the Mac dev machine, hooks enforce this: file writes into the primary
  checkout or into another session's worktree are blocked (the primary only ever
  receives ff-merges). If EnterWorktree's binding goes stale, check out your new
  branch inside your existing session worktree instead of fighting the guard.

## Test agreements

- Python: strict red-green-refactor TDD; `.venv/bin/python -m pytest` — zero
  failures, errors, or skips before every commit.
- Swift pure logic: `cd ios/HighdeasKit && swift test`. The audio/hardware layer
  is verified on the device or simulator, not fake-TDD'd.
- Keep `.env.example`, the README config table, and `pyproject.toml` in sync with
  what the code reads.

## Where the story lives

- `README.md` — what the system is and how each piece is operated.
- `docs/ios-app-handoff.md` — the phone capture app: decisions, wire contract.
- `docs/mac-peer.md` — no-special-machine Highdeas: the shared store, Syncthing,
  fan-out push; decisions and hazards, several learned the hard way.
