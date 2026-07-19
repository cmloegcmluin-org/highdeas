"""scripts/backfill_drive_subfolders.py never runs against anything but fixtures
here — see the module docstring for why processed_at is the right timestamp to
reconstruct a subfolder name from, and why that name matches DriveMusicRouter.route()
byte-for-byte."""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from backfill_drive_subfolders import compute_subfolder, eligible_memos, main, plan_backfill, run_backfill
from highdeas.routers import DriveMusicRouter
from highdeas.store import FolderStore, Memo

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "backfill_drive_subfolders.py"


def _drive_memo(audio_filename, **fields):
    fields.setdefault("route", "drive")
    fields.setdefault("status", "processed")
    return Memo(audio_filename=audio_filename, **fields)


def test_eligible_memos_selects_only_drive_routed_memos_with_a_blank_subfolder(tmp_path):
    store = FolderStore(tmp_path / "state")
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))  # eligible
    store.upsert(_drive_memo("b.m4a", processed_at="2026-07-08T00:00:00",
                             drive_subfolder="_2026_07_08_NOT_YET_PROCESSED_MUSIC"))  # already filled in
    store.upsert(Memo(audio_filename="c.m4a", route="notesnook", status="processed",
                      processed_at="2026-07-07T13:37:04"))  # wrong route
    store.upsert(_drive_memo("d.m4a", status="pending", processed_at=""))  # not routed yet

    names = {memo.audio_filename for memo in eligible_memos(store)}

    assert names == {"a.m4a", "d.m4a"}


def test_compute_subfolder_reconstructs_the_dated_name_from_processed_at():
    memo = _drive_memo("a.m4a", processed_at="2026-07-07T13:37:04")

    assert compute_subfolder(memo) == "_2026_07_07_NOT_YET_PROCESSED_MUSIC"


def test_compute_subfolder_is_none_when_processed_at_is_blank():
    memo = _drive_memo("a.m4a", status="pending", processed_at="")

    assert compute_subfolder(memo) is None


def test_compute_subfolder_is_none_when_processed_at_is_unparseable():
    memo = _drive_memo("a.m4a", processed_at="not-a-timestamp")

    assert compute_subfolder(memo) is None


def test_compute_subfolder_is_none_when_processed_at_is_not_a_string():
    # A hand-edited or externally-written state file could hold a JSON number here
    # instead of a string. datetime.fromisoformat() raises TypeError (not ValueError)
    # for a non-str argument -- must be reported as unresolved, not crash the run.
    memo = _drive_memo("a.m4a", processed_at=12345)

    assert compute_subfolder(memo) is None


def test_computed_subfolder_matches_what_the_router_would_have_produced(tmp_path):
    # Same date, two different paths — DriveMusicRouter.route() live, compute_subfolder
    # from a stored processed_at — must land on the exact same subfolder name, since
    # that's the whole premise of the backfill: no need to guess, route()'s own logic
    # (drive_subfolder_name/DATE_FORMAT in routers.py) is reused, not reimplemented.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "v.m4a").write_bytes(b"AUDIO")
    router = DriveMusicRouter(inbox, tmp_path / "drive", today=lambda: "2026_07_07",
                              write_doc=lambda path, text: None)

    outcome = router.route(Memo(audio_filename="v.m4a", transcript=""))
    memo = _drive_memo("v.m4a", processed_at="2026-07-07T13:37:04")

    assert compute_subfolder(memo) == outcome["drive_subfolder"]


def test_plan_backfill_separates_computable_changes_from_unresolved(tmp_path):
    store = FolderStore(tmp_path / "state")
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))
    store.upsert(_drive_memo("mystery.m4a", processed_at=""))

    changes, unresolved = plan_backfill(store)

    assert [(memo.audio_filename, subfolder) for memo, subfolder in changes] == [
        ("a.m4a", "_2026_07_07_NOT_YET_PROCESSED_MUSIC")
    ]
    assert unresolved == ["mystery.m4a"]


def test_dry_run_prints_planned_changes_and_writes_nothing(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))
    lines = []

    changes, unresolved = run_backfill(state, dry_run=True, out=lines.append)

    assert lines == ["a.m4a -> _2026_07_07_NOT_YET_PROCESSED_MUSIC"]
    assert len(changes) == 1
    assert unresolved == []
    assert FolderStore(state).get("a.m4a").drive_subfolder == ""
    assert not (state / ".backfill_backups").exists()


def test_dry_run_still_reports_unresolved_memos(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("mystery.m4a", processed_at=""))
    errors = []

    changes, unresolved = run_backfill(state, dry_run=True, out=lambda s: None, err=errors.append)

    assert changes == []
    assert unresolved == ["mystery.m4a"]
    assert any("mystery.m4a" in line for line in errors)


def test_real_run_writes_the_computed_subfolder(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))

    changes, unresolved = run_backfill(state, dry_run=False, out=lambda s: None)

    assert len(changes) == 1
    assert unresolved == []
    assert FolderStore(state).get("a.m4a").drive_subfolder == "_2026_07_07_NOT_YET_PROCESSED_MUSIC"


def test_real_run_leaves_ineligible_memos_untouched(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("already.m4a", processed_at="2026-07-07T13:37:04",
                             drive_subfolder="_2026_06_01_NOT_YET_PROCESSED_MUSIC"))
    store.upsert(Memo(audio_filename="notes.m4a", route="notesnook", status="processed",
                      processed_at="2026-07-07T13:37:04"))
    store.upsert(_drive_memo("pending.m4a", status="pending", processed_at=""))

    run_backfill(state, dry_run=False, out=lambda s: None)

    fresh = FolderStore(state)
    assert fresh.get("already.m4a").drive_subfolder == "_2026_06_01_NOT_YET_PROCESSED_MUSIC"
    assert fresh.get("notes.m4a").drive_subfolder == ""
    assert fresh.get("pending.m4a").drive_subfolder == ""


def test_real_run_skips_and_reports_an_eligible_memo_with_no_usable_timestamp(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("mystery.m4a", status="pending", processed_at=""))
    errors = []

    changes, unresolved = run_backfill(state, dry_run=False, out=lambda s: None, err=errors.append)

    assert changes == []
    assert unresolved == ["mystery.m4a"]
    assert any("mystery.m4a" in line for line in errors)
    assert FolderStore(state).get("mystery.m4a").drive_subfolder == ""


def test_a_memo_with_a_non_string_processed_at_is_reported_not_crashed(tmp_path):
    # One bad record (e.g. a hand-edited state file) must not take the whole run down --
    # every other memo still has to get processed, backed up, and written normally.
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("weird.m4a", processed_at=12345))
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))
    errors = []

    changes, unresolved = run_backfill(state, dry_run=False, out=lambda s: None, err=errors.append)

    assert unresolved == ["weird.m4a"]
    assert [memo.audio_filename for memo, _ in changes] == ["a.m4a"]
    assert FolderStore(state).get("a.m4a").drive_subfolder == "_2026_07_07_NOT_YET_PROCESSED_MUSIC"
    assert FolderStore(state).get("weird.m4a").drive_subfolder == ""


def test_real_run_warns_rather_than_overclaims_when_a_memo_vanishes_mid_write(tmp_path, monkeypatch):
    # Narrow race: something else (a concurrent Syncthing sync, a human) deletes a
    # memo's state file in the moment between planning the change and writing it.
    # FolderStore.update() on a since-vanished file is a silent no-op, so the script
    # must notice and say so instead of reporting a change that didn't actually land.
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))
    real_update = FolderStore.update

    def vanish_then_update(self, audio_filename, **changes):
        (Path(state) / f"{audio_filename}.json").unlink()
        return real_update(self, audio_filename, **changes)

    monkeypatch.setattr(FolderStore, "update", vanish_then_update)
    errors = []

    changes, unresolved = run_backfill(state, dry_run=False, out=lambda s: None, err=errors.append)

    assert changes == []  # not counted as applied -- it wasn't
    assert any("a.m4a" in line and "vanish" in line.lower() for line in errors)
    assert FolderStore(state).get("a.m4a") is None  # genuinely gone; script didn't resurrect it


def test_running_twice_is_idempotent(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))

    first_changes, _ = run_backfill(state, dry_run=False, out=lambda s: None)
    second_changes, second_unresolved = run_backfill(state, dry_run=False, out=lambda s: None)

    assert len(first_changes) == 1
    assert second_changes == []
    assert second_unresolved == []
    assert FolderStore(state).get("a.m4a").drive_subfolder == "_2026_07_07_NOT_YET_PROCESSED_MUSIC"
    # Only the first run had anything to back up.
    backups = list((state / ".backfill_backups").iterdir())
    assert len(backups) == 1


def test_real_run_backs_up_each_changed_state_file_before_writing(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))
    original_bytes = (state / "a.m4a.json").read_bytes()

    run_backfill(state, dry_run=False, out=lambda s: None,
                now=lambda: datetime(2026, 7, 19, 9, 30, 0))

    backups = list((state / ".backfill_backups").rglob("a.m4a.json"))
    assert len(backups) == 1
    assert "20260719_093000" in str(backups[0])
    # The backup holds the PRE-change content, not the new drive_subfolder.
    assert backups[0].read_bytes() == original_bytes


def test_a_run_with_nothing_to_change_writes_no_backup(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(Memo(audio_filename="notes.m4a", route="notesnook", status="processed",
                      processed_at="2026-07-07T13:37:04"))

    changes, unresolved = run_backfill(state, dry_run=False, out=lambda s: None)

    assert changes == []
    assert unresolved == []
    assert not (state / ".backfill_backups").exists()


def test_cli_dry_run_prints_exactly_the_planned_changes(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(state), "--dry-run"],
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.splitlines() == ["a.m4a -> _2026_07_07_NOT_YET_PROCESSED_MUSIC"]
    assert FolderStore(state).get("a.m4a").drive_subfolder == ""


def test_cli_real_run_writes_and_summarizes(tmp_path):
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(state)],
        capture_output=True, text=True, check=True,
    )

    # stdout carries exactly the change data, in dry-run or real mode alike; the
    # summary is diagnostic text, so it goes to stderr rather than mixing into stdout.
    assert result.stdout.splitlines() == ["a.m4a -> _2026_07_07_NOT_YET_PROCESSED_MUSIC"]
    assert "1" in result.stderr.splitlines()[-1]
    assert FolderStore(state).get("a.m4a").drive_subfolder == "_2026_07_07_NOT_YET_PROCESSED_MUSIC"


def test_run_backfill_refuses_a_state_dir_that_does_not_exist(tmp_path):
    # FolderStore silently mkdir's whatever path it's given, which would otherwise turn
    # a typo'd path into a quiet, indistinguishable-from-success "0 changes" instead of
    # a clear error — exactly the kind of mistake that matters on a real state dir.
    missing = tmp_path / "does-not-exist"

    with pytest.raises(FileNotFoundError):
        run_backfill(missing, dry_run=True, out=lambda s: None)

    assert not missing.exists()


def test_cli_refuses_a_state_dir_that_does_not_exist(tmp_path):
    missing = tmp_path / "does-not-exist"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(missing), "--dry-run"],
        capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "does-not-exist" in result.stderr
    assert not missing.exists()


def test_main_never_runs_against_anything_outside_the_given_state_dir(tmp_path, monkeypatch):
    # Cheap but real guardrail: main() only ever touches the path it's given.
    state = tmp_path / "state"
    store = FolderStore(state)
    store.upsert(_drive_memo("a.m4a", processed_at="2026-07-07T13:37:04"))
    calls = []
    monkeypatch.setattr(
        "backfill_drive_subfolders.run_backfill",
        lambda state_dir, **kwargs: calls.append(state_dir) or ([], []),
    )

    main([str(state), "--dry-run"])

    assert calls == [str(state)]
