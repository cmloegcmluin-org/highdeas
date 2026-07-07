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
        find_new=find_new,
        clock=lambda: "2026-07-07T00:00",
    )

    service.refresh()

    pending = store.list_by_status("pending")
    assert [m.audio_filename for m in pending] == ["a.m4a", "b.m4a"]
    assert store.get("a.m4a").transcript == "text for a.m4a"
    assert store.get("a.m4a").created_at == "2026-07-07T00:00"


def test_submit_routes_then_marks_processed(tmp_path):
    store = MemoStore(tmp_path / "memos.db")
    store.upsert(Memo(audio_filename="a.m4a", route="drive", status="pending"))
    routed = []

    service = ReviewService(
        inbox_dir="/inbox",
        store=store,
        transcriber=FakeTranscriber(),
        route=lambda memo: routed.append((memo.audio_filename, memo.route)),
        clock=lambda: "2026-07-07T05:00",
    )

    service.submit("a.m4a")

    assert routed == [("a.m4a", "drive")]
    memo = store.get("a.m4a")
    assert memo.status == "processed"
    assert memo.processed_at == "2026-07-07T05:00"
