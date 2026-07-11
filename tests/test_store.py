import json
import sqlite3
import threading

import pytest

from highdeas.store import FolderStore, Memo, MemoStore


@pytest.fixture(params=["sqlite", "folder"])
def store(request, tmp_path):
    """Every behavior here is a contract BOTH stores honor: the SQLite store
    that runs a single machine, and the folder store whose per-memo files a
    sync engine carries between machines (docs/mac-peer.md)."""
    if request.param == "sqlite":
        return MemoStore(tmp_path / "memos.db")
    return FolderStore(tmp_path / "state")


def test_upsert_then_get_roundtrips(store):
    memo = Memo(
        audio_filename="voice-4.m4a",
        transcript="hello",
        name="An idea",
        created_at="2026-07-07T02:12:00",
    )

    store.upsert(memo)

    assert store.get("voice-4.m4a") == memo


def test_recorded_at_roundtrips(store):
    store.upsert(Memo(audio_filename="a.m4a", recorded_at="2026-07-07T13:37:04"))

    assert store.get("a.m4a").recorded_at == "2026-07-07T13:37:04"


def test_get_unknown_returns_none(store):
    assert store.get("nope.m4a") is None


def test_store_migrates_a_db_created_before_the_newer_columns_existed(tmp_path):
    # Opening a memos.db from an older version must add every column since added,
    # each with the type it needs — position sorts numerically only as an INTEGER.
    db = tmp_path / "memos.db"
    legacy = sqlite3.connect(db)
    legacy.execute(
        "CREATE TABLE memos (audio_filename TEXT PRIMARY KEY, transcript TEXT, "
        "name TEXT, route TEXT, status TEXT, created_at TEXT, processed_at TEXT)"
    )
    legacy.commit()
    legacy.close()

    store = MemoStore(db)
    names = [f"{i}.m4a" for i in range(12)]
    for filename in names:
        store.upsert(Memo(audio_filename=filename, status="pending",
                          recorded_at="2026-07-07T13:37:04"))
    store.reorder(names)

    assert store.get("0.m4a").recorded_at == "2026-07-07T13:37:04"
    assert [m.audio_filename for m in store.list_pending()] == names


def test_known_filenames_returns_stored_filenames(store):
    store.upsert(Memo(audio_filename="a.m4a"))
    store.upsert(Memo(audio_filename="b.m4a"))

    assert store.known_filenames() == {"a.m4a", "b.m4a"}


def test_list_pending_filters_and_orders_by_recorded_at(store):
    # Order by when each memo was recorded, not when it was ingested, so the inbox
    # list always reads oldest-to-newest. Ingestion order can't be trusted: a startup
    # catch-up scans the inbox by filename (voice-10 before voice-2), which is neither
    # recording order nor consistent with the live poll's arrival order.
    store.upsert(Memo(audio_filename="b.m4a", status="pending",
                      recorded_at="2026-07-07T02:00", created_at="2026-07-07T08:00"))
    store.upsert(Memo(audio_filename="a.m4a", status="pending",
                      recorded_at="2026-07-07T01:00", created_at="2026-07-07T09:00"))
    store.upsert(Memo(audio_filename="done.m4a", status="processed",
                      recorded_at="2026-07-07T03:00"))

    pending = store.list_pending()

    # a was recorded first though ingested last, so it still sorts ahead of b.
    assert [m.audio_filename for m in pending] == ["a.m4a", "b.m4a"]


def test_reorder_pins_pending_memos_to_the_given_order(store):
    # Dragging a row rewrites the pending order, overriding recorded time.
    store.upsert(Memo(audio_filename="a.m4a", status="pending", recorded_at="2026-07-07T01:00"))
    store.upsert(Memo(audio_filename="b.m4a", status="pending", recorded_at="2026-07-07T02:00"))
    store.upsert(Memo(audio_filename="c.m4a", status="pending", recorded_at="2026-07-07T03:00"))

    store.reorder(["c.m4a", "a.m4a", "b.m4a"])

    assert [m.audio_filename for m in store.list_pending()] == ["c.m4a", "a.m4a", "b.m4a"]


def test_a_memo_with_no_position_lists_after_the_reordered_ones(store):
    # A recording that arrives after the user has arranged the inbox joins the end,
    # rather than jumping into the middle on its recorded time.
    store.upsert(Memo(audio_filename="a.m4a", status="pending", recorded_at="2026-07-07T01:00"))
    store.upsert(Memo(audio_filename="b.m4a", status="pending", recorded_at="2026-07-07T02:00"))
    store.reorder(["b.m4a", "a.m4a"])

    store.upsert(Memo(audio_filename="fresh.m4a", status="pending", recorded_at="2026-07-07T00:30"))

    assert [m.audio_filename for m in store.list_pending()] == [
        "b.m4a", "a.m4a", "fresh.m4a"]


def test_reorder_stays_numeric_past_the_tenth_memo(store):
    # Positions must compare as numbers: as text, '10' would sort between '1' and '2'.
    names = [f"{i}.m4a" for i in range(12)]
    for filename in names:
        store.upsert(Memo(audio_filename=filename, status="pending"))

    store.reorder(names)

    assert [m.audio_filename for m in store.list_pending()] == names


def test_update_changes_named_fields_only(store):
    store.upsert(Memo(audio_filename="a.m4a", name="", transcript="raw", route="notesnook"))

    store.update("a.m4a", name="Better name", transcript="edited", route="drive")

    memo = store.get("a.m4a")
    assert memo.name == "Better name"
    assert memo.transcript == "edited"
    assert memo.route == "drive"
    assert memo.status == "pending"  # untouched


def test_store_is_usable_from_another_thread(store):
    # The Flask dev server handles each request in a new thread, so the store
    # must not be pinned to the thread that created it.
    store.upsert(Memo(audio_filename="a.m4a"))
    result = {}

    def worker():
        try:
            result["names"] = store.known_filenames()
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert result.get("error") is None, result.get("error")
    assert result["names"] == {"a.m4a"}


def test_rekey_changes_the_primary_key_keeping_other_fields(store):
    store.upsert(Memo(audio_filename="raw.m4a", transcript="t", name="n", status="deleted"))

    store.rekey("raw.m4a", "raw-abc123abc123.m4a")

    assert store.get("raw.m4a") is None
    memo = store.get("raw-abc123abc123.m4a")
    assert memo.transcript == "t"
    assert memo.name == "n"
    assert memo.status == "deleted"


def test_remove_deletes_the_record(store):
    store.upsert(Memo(audio_filename="a.m4a"))

    store.remove("a.m4a")

    assert store.get("a.m4a") is None


# --- FolderStore only: the shapes a sync engine leaves behind ---


def test_folder_store_keeps_one_json_per_memo_and_no_scraps(tmp_path):
    store = FolderStore(tmp_path / "state")

    store.upsert(Memo(audio_filename="a.m4a", transcript="t"))
    store.update("a.m4a", name="Named")

    files = sorted(p.name for p in (tmp_path / "state").iterdir())
    # Atomic writes leave the memo's file and nothing else — no .tmp scraps a
    # crash (or the sync engine) could mistake for state.
    assert files == ["a.m4a.json"]


def test_folder_store_skips_a_sync_conflict_copy(tmp_path):
    # When both machines edit one memo before syncing, Syncthing keeps the loser
    # as a *.sync-conflict-*.json beside the winner. Reading it as its own memo
    # would resurrect the losing write as a phantom twin.
    store = FolderStore(tmp_path / "state")
    store.upsert(Memo(audio_filename="a.m4a", name="winner"))
    conflict = tmp_path / "state" / "a.m4a.sync-conflict-20260711-000101-ABCDEF.json"
    losing = json.loads((tmp_path / "state" / "a.m4a.json").read_text())
    losing["name"] = "loser"
    conflict.write_text(json.dumps(losing))

    assert store.known_filenames() == {"a.m4a"}
    assert store.get("a.m4a").name == "winner"
    assert [m.name for m in store.list_pending()] == ["winner"]


def test_folder_store_survives_a_half_synced_or_foreign_file(tmp_path):
    # A file mid-flight from the other machine can be truncated garbage for a
    # moment; a stray non-memo JSON someone drops in is not ours. Neither may
    # crash a scan or become a memo.
    store = FolderStore(tmp_path / "state")
    store.upsert(Memo(audio_filename="a.m4a"))
    (tmp_path / "state" / "torn.m4a.json").write_bytes(b'{"audio_filename": "torn.m')
    (tmp_path / "state" / "notes.json").write_text('{"unrelated": true}')

    assert store.known_filenames() == {"a.m4a"}


def test_folder_store_ignores_fields_from_a_newer_version(tmp_path):
    # The other machine may run a newer Highdeas that writes fields this one
    # doesn't know. They must not break reading — same spirit as the SQLite
    # store's column migration, pointed the other way.
    store = FolderStore(tmp_path / "state")
    store.upsert(Memo(audio_filename="a.m4a", name="kept"))
    path = tmp_path / "state" / "a.m4a.json"
    data = json.loads(path.read_text())
    data["from_the_future"] = "🛸"
    path.write_text(json.dumps(data))

    assert store.get("a.m4a").name == "kept"
