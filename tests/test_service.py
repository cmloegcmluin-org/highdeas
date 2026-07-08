from pathlib import Path

from voicememo.service import ReviewService
from voicememo.store import Memo, MemoStore


class FakeTranscriber:
    def transcribe(self, path):
        return f"text for {Path(path).name}"


def test_refresh_transcribes_new_recordings_into_pending(tmp_path):
    store = MemoStore(tmp_path / "memos.db")

    def find_new(inbox, known):
        return [Path("/inbox/a.m4a"), Path("/inbox/b.m4a")]

    service = ReviewService(
        inbox_dir="/inbox",
        store=store,
        transcriber=FakeTranscriber(),
        bin_dir=tmp_path / "bin",
        find_new=find_new,
        clock=lambda: "2026-07-07T00:00",
        recorded_time=lambda path: f"recorded-{Path(path).name}",
    )

    service.refresh()

    pending = store.list_by_status("pending")
    assert [m.audio_filename for m in pending] == ["a.m4a", "b.m4a"]
    assert store.get("a.m4a").transcript == "text for a.m4a"
    assert store.get("a.m4a").created_at == "2026-07-07T00:00"
    assert store.get("a.m4a").recorded_at == "recorded-a.m4a"


def test_submit_routes_then_marks_processed(tmp_path):
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", route="drive", status="pending"))
    routed = []

    service = ReviewService(
        inbox_dir="/inbox",
        store=store,
        transcriber=FakeTranscriber(),
        bin_dir=tmp_path / "bin",
        route=lambda memo: routed.append((memo.audio_filename, memo.route)),
        clock=lambda: "2026-07-07T05:00",
    )

    service.submit("a.m4a")

    assert routed == [("a.m4a", "drive")]
    memo = store.get("a.m4a")
    assert memo.status == "processed"
    assert memo.processed_at == "2026-07-07T05:00"


def test_delete_marks_memo_deleted(tmp_path):
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", status="pending"))

    service = ReviewService(
        inbox_dir="/inbox",
        store=store,
        transcriber=FakeTranscriber(),
        bin_dir=tmp_path / "bin",
        clock=lambda: "2026-07-07T06:00",
    )

    service.delete("a.m4a")

    memo = store.get("a.m4a")
    assert memo.status == "deleted"
    assert memo.processed_at == "2026-07-07T06:00"


def test_submit_retires_inbox_audio_to_bin_when_route_leaves_it(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bin_dir = tmp_path / "bin"
    (inbox / "a.m4a").write_bytes(b"AUDIO")
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", route="notesnook", status="pending"))

    service = ReviewService(
        inbox_dir=inbox, store=store, transcriber=FakeTranscriber(),
        bin_dir=bin_dir, route=lambda memo: None, clock=lambda: "T",
    )
    service.submit("a.m4a")

    assert not (inbox / "a.m4a").exists()
    assert (bin_dir / "a.m4a").read_bytes() == b"AUDIO"
    assert store.get("a.m4a").status == "processed"


def test_submit_leaves_bin_untouched_when_route_already_moved_audio(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bin_dir = tmp_path / "bin"
    (inbox / "a.m4a").write_bytes(b"AUDIO")
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", route="drive", status="pending"))

    def drive_route(memo):  # a Drive route moves the audio out of the inbox itself
        (inbox / "a.m4a").rename(tmp_path / "moved_to_drive.m4a")

    service = ReviewService(
        inbox_dir=inbox, store=store, transcriber=FakeTranscriber(),
        bin_dir=bin_dir, route=drive_route, clock=lambda: "T",
    )
    service.submit("a.m4a")

    assert not bin_dir.exists() or list(bin_dir.iterdir()) == []


def test_delete_retires_inbox_audio_to_bin(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bin_dir = tmp_path / "bin"
    (inbox / "a.m4a").write_bytes(b"AUDIO")
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", status="pending"))

    ReviewService(inbox_dir=inbox, store=store, transcriber=FakeTranscriber(),
                  bin_dir=bin_dir, clock=lambda: "T").delete("a.m4a")

    assert not (inbox / "a.m4a").exists()
    assert (bin_dir / "a.m4a").read_bytes() == b"AUDIO"
    assert store.get("a.m4a").status == "deleted"


def test_binned_lists_processed_and_deleted_with_audio_in_bin_newest_first(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "n.m4a").write_bytes(b"N")
    (bin_dir / "d.m4a").write_bytes(b"D")
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="n.m4a", status="processed", route="notesnook", processed_at="2026-07-07T02:00"))
    store.upsert(Memo(audio_filename="d.m4a", status="deleted", processed_at="2026-07-07T03:00"))
    store.upsert(Memo(audio_filename="music.m4a", status="processed", route="drive", processed_at="2026-07-07T04:00"))
    store.upsert(Memo(audio_filename="p.m4a", status="pending"))

    service = ReviewService(inbox_dir=inbox, store=store, transcriber=FakeTranscriber(), bin_dir=bin_dir)

    # music.m4a (Drive) lives in Drive not the bin, so it is excluded; pending excluded; newest first
    assert [m.audio_filename for m in service.binned()] == ["d.m4a", "n.m4a"]


def test_restore_moves_audio_back_to_inbox_and_marks_pending(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "a.m4a").write_bytes(b"A")
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", status="deleted", processed_at="2026-07-07T03:00"))

    ReviewService(inbox_dir=inbox, store=store, transcriber=FakeTranscriber(), bin_dir=bin_dir).restore("a.m4a")

    assert (inbox / "a.m4a").read_bytes() == b"A"
    assert not (bin_dir / "a.m4a").exists()
    memo = store.get("a.m4a")
    assert memo.status == "pending"
    assert memo.processed_at == ""


def test_purge_expired_removes_only_bin_items_past_retention(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "old.m4a").write_bytes(b"OLD")
    (bin_dir / "new.m4a").write_bytes(b"NEW")
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="old.m4a", status="processed", processed_at="2026-04-01T00:00:00"))
    store.upsert(Memo(audio_filename="new.m4a", status="deleted", processed_at="2026-06-30T00:00:00"))

    service = ReviewService(inbox_dir=inbox, store=store, transcriber=FakeTranscriber(),
                            bin_dir=bin_dir, clock=lambda: "2026-07-07T00:00:00")
    service.purge_expired(retention_days=90)

    # cutoff is 2026-04-08; "old" is before it -> audio and record gone
    assert not (bin_dir / "old.m4a").exists()
    assert store.get("old.m4a") is None
    # "new" is within retention -> untouched
    assert (bin_dir / "new.m4a").exists()
    assert store.get("new.m4a") is not None


def test_refresh_purges_expired_bin_items(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "old.m4a").write_bytes(b"OLD")
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="old.m4a", status="processed", processed_at="2026-01-01T00:00:00"))

    service = ReviewService(inbox_dir=inbox, store=store, transcriber=FakeTranscriber(),
                            bin_dir=bin_dir, find_new=lambda inbox, known: [],
                            clock=lambda: "2026-07-07T00:00:00")
    service.refresh()

    assert store.get("old.m4a") is None
    assert not (bin_dir / "old.m4a").exists()
