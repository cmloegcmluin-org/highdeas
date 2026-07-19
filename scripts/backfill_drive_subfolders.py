"""Retroactively fills in Memo.drive_subfolder for memos that were routed to Google
Drive before that field was tracked (or before this feature existed at all) — see the
comment on Memo.drive_subfolder in src/highdeas/store.py. Without it, those memos' Bin
Drive icon permanently falls back to the top-level Drive folder instead of the dated
subfolder the memo actually landed in.

The subfolder name is fully programmatic, so it can be reconstructed after the fact
with no new recording needed:

  - DriveMusicRouter.route() (src/highdeas/routers.py) names it from the date it ran,
    via drive_subfolder_name(DATE_FORMAT string) — a free function, not just an inline
    f-string, specifically so it has exactly one implementation to reuse here.
  - InboxService._retire() (src/highdeas/service.py) stamps processed_at with that same
    clock call, in the very store.update() that persists the fields route() returned:
        outcome = self._route(memo)                                   # submit()
        self._retire(audio_filename, "processed", **outcome)
        ...
        store.update(audio_filename, status=status, processed_at=self._clock(), **fields)
    So for any memo whose route is "drive", processed_at IS the moment route() ran —
    confirmed by reading that merge, not assumed.

That means a memo's own stored processed_at is enough to recompute the exact subfolder
route() produced that day: parse it, format it with the same DATE_FORMAT, and hand it to
the same drive_subfolder_name(). Byte-for-byte identical to what route() built, because
it's the same code, not a reimplementation that could drift.

Usage:
    python scripts/backfill_drive_subfolders.py <state_dir> [--dry-run]

<state_dir> is a HIGHDEAS_STATE_DIR folder — highdeas.store.FolderStore's one-JSON-file-
per-memo layout (see docs/mac-peer.md). Only memos with route="drive" and a blank
drive_subfolder are touched; everything else is left exactly as it is. Among those, a
memo with no usable processed_at (never actually routed yet, or predates that field too)
is always reported and skipped — never guessed at. Safe to run twice: a memo this script
already filled in no longer qualifies, so a second run changes nothing and backs up
nothing. Every real (non-dry-run) run backs up each state file it's about to modify
first, automatically, before writing it.
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highdeas.routers import DATE_FORMAT, drive_subfolder_name  # noqa: E402
from highdeas.store import FolderStore  # noqa: E402


def eligible_memos(store):
    """Every memo routed to Drive with no drive_subfolder on record — the backfill's
    candidate set. Includes a memo still waiting on its first-ever Drive submission
    (blank drive_subfolder is correct there too); compute_subfolder tells those apart
    from real backfill targets by way of having no processed_at to compute from."""
    return [memo for memo in (*store.list_pending(), *store.list_retired())
            if memo.route == "drive" and not memo.drive_subfolder]


def compute_subfolder(memo):
    """The subfolder DriveMusicRouter.route() produced for this memo, recovered from
    its own processed_at — or None when that timestamp is missing or unparseable, so
    the caller can report it instead of guessing."""
    if not memo.processed_at:
        return None
    try:
        routed_when = datetime.fromisoformat(memo.processed_at)
    except ValueError:
        return None
    return drive_subfolder_name(routed_when.strftime(DATE_FORMAT))


def plan_backfill(store):
    """The (memo, subfolder) pairs this run can confidently fill in, and the
    audio_filenames of eligible memos it can't (no usable processed_at)."""
    changes, unresolved = [], []
    for memo in eligible_memos(store):
        subfolder = compute_subfolder(memo)
        if subfolder is None:
            unresolved.append(memo.audio_filename)
        else:
            changes.append((memo, subfolder))
    return changes, unresolved


def _backup(state_dir, audio_filenames, when):
    """Copy each about-to-change memo's state file into a timestamped backup folder
    before anything is overwritten. Lives inside state_dir but under a dotted name, so
    FolderStore's own "*.json" glob (non-recursive) never mistakes a backup for a
    memo. Returns the backup folder actually used."""
    backup_dir = Path(state_dir) / ".backfill_backups" / when.strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for audio_filename in audio_filenames:
        source = Path(state_dir) / f"{audio_filename}.json"
        if source.exists():
            shutil.copy2(source, backup_dir / source.name)
    return backup_dir


def _stderr(line):
    print(line, file=sys.stderr)


def run_backfill(state_dir, *, dry_run=False, now=datetime.now, out=print, err=_stderr):
    """Fill in drive_subfolder for every memo this run can resolve, returning
    (changes, unresolved) exactly as planned — even in dry-run mode, where nothing is
    written. `out` gets exactly one line per change (audio_filename -> subfolder) and
    nothing else, so dry-run's stdout is exactly what the task asks for: precisely what
    would change. `err` gets everything else — skipped memos and the backup notice —
    diagnostic text, not data."""
    # FolderStore itself silently mkdir's whatever path it's given (right for the app,
    # which should always have somewhere to write), which would otherwise turn a
    # typo'd state_dir into an indistinguishable-from-success "0 changes" here instead
    # of a clear error — worth refusing loudly given what this runs against for real.
    if not Path(state_dir).is_dir():
        raise FileNotFoundError(f"No such state directory: {state_dir}")
    store = FolderStore(state_dir)
    changes, unresolved = plan_backfill(store)

    for memo, subfolder in changes:
        out(f"{memo.audio_filename} -> {subfolder}")
    for audio_filename in unresolved:
        err(f"SKIPPED {audio_filename}: route is drive, drive_subfolder is blank, but "
            f"processed_at isn't a usable timestamp to compute one from")

    if dry_run or not changes:
        return changes, unresolved

    backup_dir = _backup(state_dir, [memo.audio_filename for memo, _ in changes], now())
    err(f"Backed up {len(changes)} state file(s) to {backup_dir} before writing")
    for memo, subfolder in changes:
        store.update(memo.audio_filename, drive_subfolder=subfolder)
    return changes, unresolved


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Backfill drive_subfolder for memos routed to Drive before it was tracked.")
    parser.add_argument("state_dir", help="A HIGHDEAS_STATE_DIR folder (FolderStore layout).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing anything.")
    args = parser.parse_args(argv)

    try:
        changes, unresolved = run_backfill(args.state_dir, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        _stderr(str(exc))
        raise SystemExit(1) from exc

    verb = "Would change" if args.dry_run else "Changed"
    _stderr(f"{verb} {len(changes)} memo(s); {len(unresolved)} skipped.")


if __name__ == "__main__":
    main()
