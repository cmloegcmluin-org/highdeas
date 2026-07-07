import pytest

from voicememo.routers import NotesnookRouter, Router
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


def test_notesnook_router_falls_back_to_default_title_when_unnamed():
    post = FakePost()

    NotesnookRouter("K", post=post).route(Memo(audio_filename="a.m4a", name="", transcript="hi"))

    assert post.calls[0][1]["json"]["title"] == "Untitled voice note"


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
