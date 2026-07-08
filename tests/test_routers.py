from pathlib import Path

import pytest

from voicememo.routers import DriveMusicRouter, NotesnookRouter, Router
from voicememo.store import Memo


class RecordingRouter:
    def __init__(self):
        self.routed = []

    def route(self, memo):
        self.routed.append(memo.audio_filename)


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakePost:
    def __init__(self, status_code=200):
        self.calls = []
        self._status_code = status_code

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self._status_code)


def test_notesnook_router_posts_title_and_html_body():
    post = FakePost()
    router = NotesnookRouter("MY_KEY", source="voicememo", post=post)

    router.route(Memo(audio_filename="a.m4a", name="Grocery idea", transcript="buy milk\nand eggs"))

    url, kwargs = post.calls[0]
    assert url == "https://inbox.notesnook.com/"
    assert kwargs["headers"] == {"Authorization": "MY_KEY", "Content-Type": "application/json"}
    body = kwargs["json"]
    assert body["title"] == "Grocery idea"
    assert body["type"] == "note"
    assert body["source"] == "voicememo"
    assert body["version"] == 1
    assert body["content"] == {"type": "html", "data": "<p>buy milk</p><p>and eggs</p>"}


def test_notesnook_router_titles_unnamed_memo_with_its_recording_time():
    post = FakePost()

    NotesnookRouter("K", post=post).route(
        Memo(audio_filename="a.m4a", name="", transcript="hi", recorded_at="2026-07-07T15:45:00")
    )

    # Notesnook's own "Note $date$ $time$" style, but for when the memo was recorded.
    assert post.calls[0][1]["json"]["title"] == "Note 2026-07-07 3:45 PM"


def test_notesnook_router_falls_back_to_scan_time_when_recording_time_unknown():
    post = FakePost()

    NotesnookRouter("K", post=post).route(
        Memo(audio_filename="a.m4a", name="", recorded_at="", created_at="2026-07-07T09:05:00")
    )

    assert post.calls[0][1]["json"]["title"] == "Note 2026-07-07 9:05 AM"


def test_notesnook_router_never_sends_an_empty_title():
    # The Inbox API rejects a blank title (title: z.string().min(1)), so an
    # unnamed memo with no timestamps must still get a non-empty title.
    post = FakePost()

    NotesnookRouter("K", post=post).route(Memo(audio_filename="a.m4a", name=""))

    assert post.calls[0][1]["json"]["title"]


def test_notesnook_router_raises_on_error_response():
    post = FakePost(status_code=403)

    with pytest.raises(RuntimeError):
        NotesnookRouter("K", post=post).route(Memo(audio_filename="a.m4a", name="X", transcript="y"))


def test_router_dispatches_to_notesnook_by_default():
    notesnook, drive = RecordingRouter(), RecordingRouter()

    Router(notesnook=notesnook, drive=drive)(Memo(audio_filename="a.m4a", route="notesnook"))

    assert notesnook.routed == ["a.m4a"]
    assert drive.routed == []


def test_router_dispatches_to_drive_when_selected():
    notesnook, drive = RecordingRouter(), RecordingRouter()

    Router(notesnook=notesnook, drive=drive)(Memo(audio_filename="a.m4a", route="drive"))

    assert drive.routed == ["a.m4a"]
    assert notesnook.routed == []


def test_router_skips_drive_when_not_configured():
    notesnook = RecordingRouter()

    Router(notesnook=notesnook)(Memo(audio_filename="a.m4a", route="drive"))

    assert notesnook.routed == []


def test_drive_router_moves_audio_into_dated_folder_and_writes_doc(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    drive = tmp_path / "drive"
    drive.mkdir()
    (inbox / "voice-3.m4a").write_bytes(b"AUDIO")
    docs = []

    router = DriveMusicRouter(
        inbox, drive,
        today=lambda: "2026_07_07",
        write_doc=lambda path, text: docs.append((Path(path), text)),
    )
    router.route(Memo(audio_filename="voice-3.m4a", name="Korok Dance", transcript="la la la"))

    folder = drive / "_2026_07_07_NOT_YET_PROCESSED_MUSIC"
    assert (folder / "Korok Dance.m4a").read_bytes() == b"AUDIO"
    assert not (inbox / "voice-3.m4a").exists()
    assert docs == [(folder / "Korok Dance.docx", "la la la")]


def _drive_router(inbox, drive, **kwargs):
    inbox.mkdir(exist_ok=True)
    drive.mkdir(exist_ok=True)
    return DriveMusicRouter(inbox, drive, today=lambda: "2026_07_07",
                            write_doc=kwargs.get("write_doc", lambda path, text: None))


def test_drive_router_skips_doc_when_transcript_is_blank(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "v.m4a").write_bytes(b"A")
    docs = []
    router = _drive_router(tmp_path / "inbox", tmp_path / "drive",
                           write_doc=lambda path, text: docs.append(path))

    router.route(Memo(audio_filename="v.m4a", name="Song", transcript="   "))

    assert docs == []
    assert (tmp_path / "drive" / "_2026_07_07_NOT_YET_PROCESSED_MUSIC" / "Song.m4a").exists()


def test_drive_router_sanitizes_illegal_filename_characters(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "v.m4a").write_bytes(b"A")
    router = _drive_router(tmp_path / "inbox", tmp_path / "drive")

    router.route(Memo(audio_filename="v.m4a", name='Take 1/2: "final?"', transcript=""))

    assert (tmp_path / "drive" / "_2026_07_07_NOT_YET_PROCESSED_MUSIC" / "Take 12 final.m4a").exists()


def test_drive_router_falls_back_to_audio_stem_when_unnamed(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "voice-5.m4a").write_bytes(b"A")
    router = _drive_router(tmp_path / "inbox", tmp_path / "drive")

    router.route(Memo(audio_filename="voice-5.m4a", name="", transcript=""))

    assert (tmp_path / "drive" / "_2026_07_07_NOT_YET_PROCESSED_MUSIC" / "voice-5.m4a").exists()
