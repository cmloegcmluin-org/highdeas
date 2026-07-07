from voicememo.store import Memo
from voicememo.web import create_app


class FakeService:
    def __init__(self, pending=()):
        self._pending = list(pending)
        self.refreshed = 0
        self.edits = []
        self.submitted = []

    def refresh(self):
        self.refreshed += 1

    def pending(self):
        return self._pending

    def edit(self, audio_filename, **fields):
        self.edits.append((audio_filename, fields))

    def submit(self, audio_filename):
        self.submitted.append(audio_filename)


def test_index_refreshes_and_lists_pending(tmp_path):
    service = FakeService(pending=[Memo(audio_filename="a.m4a", transcript="hello there")])
    client = create_app(service, inbox_dir=str(tmp_path)).test_client()

    resp = client.get("/")

    assert service.refreshed == 1
    assert resp.status_code == 200
    assert b"a.m4a" in resp.data
    assert b"hello there" in resp.data


def test_submit_saves_edits_then_submits_and_redirects(tmp_path):
    service = FakeService()
    client = create_app(service, inbox_dir=str(tmp_path)).test_client()

    resp = client.post("/submit/a.m4a", data={
        "name": "My idea", "transcript": "edited text", "route": "drive",
    })

    assert service.edits == [
        ("a.m4a", {"name": "My idea", "transcript": "edited text", "route": "drive"})
    ]
    assert service.submitted == ["a.m4a"]
    assert resp.status_code == 302


def test_submit_defaults_route_to_notesnook_when_toggle_off(tmp_path):
    service = FakeService()
    client = create_app(service, inbox_dir=str(tmp_path)).test_client()

    # An unchecked checkbox toggle submits no "route" field.
    client.post("/submit/a.m4a", data={"name": "X", "transcript": "Y"})

    assert service.edits == [("a.m4a", {"name": "X", "transcript": "Y", "route": "notesnook"})]


def test_audio_serves_file_from_inbox(tmp_path):
    (tmp_path / "a.m4a").write_bytes(b"AUDIODATA")
    client = create_app(FakeService(), inbox_dir=str(tmp_path)).test_client()

    resp = client.get("/audio/a.m4a")

    assert resp.status_code == 200
    assert resp.data == b"AUDIODATA"
