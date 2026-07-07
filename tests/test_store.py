from voicememo.store import Memo, MemoStore


def test_upsert_then_get_roundtrips(tmp_path):
    store = MemoStore(tmp_path / "memos.db")
    memo = Memo(
        audio_filename="voice-4.m4a",
        transcript="hello",
        name="An idea",
        created_at="2026-07-07T02:12:00",
    )

    store.upsert(memo)

    assert store.get("voice-4.m4a") == memo


def test_get_unknown_returns_none(tmp_path):
    store = MemoStore(tmp_path / "memos.db")

    assert store.get("nope.m4a") is None


def test_known_filenames_returns_stored_filenames(tmp_path):
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a"))
    store.upsert(Memo(audio_filename="b.m4a"))

    assert store.known_filenames() == {"a.m4a", "b.m4a"}


def test_list_by_status_filters_and_orders_by_created_at(tmp_path):
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="b.m4a", status="pending", created_at="2026-07-07T02:00"))
    store.upsert(Memo(audio_filename="a.m4a", status="pending", created_at="2026-07-07T01:00"))
    store.upsert(Memo(audio_filename="done.m4a", status="processed", created_at="2026-07-07T03:00"))

    pending = store.list_by_status("pending")

    assert [m.audio_filename for m in pending] == ["a.m4a", "b.m4a"]


def test_update_changes_named_fields_only(tmp_path):
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", name="", transcript="raw", route="notesnook"))

    store.update("a.m4a", name="Better name", transcript="edited", route="drive")

    memo = store.get("a.m4a")
    assert memo.name == "Better name"
    assert memo.transcript == "edited"
    assert memo.route == "drive"
    assert memo.status == "pending"  # untouched
