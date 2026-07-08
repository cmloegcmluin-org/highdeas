from voicememo.store import Memo
from voicememo.web import create_app


class FakeService:
    def __init__(self, pending=(), binned=()):
        self._pending = list(pending)
        self._binned = list(binned)
        self.refreshed = 0
        self.edits = []
        self.submitted = []
        self.deleted = []
        self.restored = []

    def refresh(self):
        self.refreshed += 1

    def pending(self):
        return self._pending

    def edit(self, audio_filename, **fields):
        self.edits.append((audio_filename, fields))

    def submit(self, audio_filename):
        self.submitted.append(audio_filename)

    def delete(self, audio_filename):
        self.deleted.append(audio_filename)

    def binned(self):
        return self._binned

    def restore(self, audio_filename):
        self.restored.append(audio_filename)


def test_index_refreshes_and_lists_pending(tmp_path):
    service = FakeService(pending=[Memo(audio_filename="a.m4a", transcript="hello there")])
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    resp = client.get("/")

    assert service.refreshed == 1
    assert resp.status_code == 200
    assert b"a.m4a" in resp.data
    assert b"hello there" in resp.data


def test_index_renders_highdeas_controls(tmp_path):
    service = FakeService(pending=[Memo(audio_filename="a.m4a", transcript="hi", name="Idea")])
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    body = client.get("/").data

    # Rebranded title + header.
    assert b"<title>Highdeas</title>" in body
    assert b"Highdeas" in body
    # Bulk actions live beside the Bin link.
    assert b"Submit all" in body
    assert b"Trash all" in body
    assert b'href="/bin"' in body
    # Each row carries its filename so JS can target /edit, /submit, /delete.
    assert b'data-file="a.m4a"' in body
    # The "copy transcript into name" control between Transcript and Name.
    assert b'class="copy"' in body
    # The delete confirmation popup is gone.
    assert b"confirm(" not in body


def test_submit_saves_edits_then_submits_and_returns_204(tmp_path):
    service = FakeService()
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    resp = client.post("/submit/a.m4a", data={
        "name": "My idea", "transcript": "edited text", "route": "drive",
    })

    # Submit flushes the row's current field values before submitting.
    assert service.edits == [
        ("a.m4a", {"name": "My idea", "transcript": "edited text", "route": "drive"})
    ]
    assert service.submitted == ["a.m4a"]
    # 204 (no redirect): the client removes the row optimistically, no page reload.
    assert resp.status_code == 204


def test_submit_defaults_route_to_notesnook_when_toggle_off(tmp_path):
    service = FakeService()
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    # An unchecked checkbox toggle submits no "route" field.
    client.post("/submit/a.m4a", data={"name": "X", "transcript": "Y"})

    assert service.edits == [("a.m4a", {"name": "X", "transcript": "Y", "route": "notesnook"})]


def test_edit_route_saves_fields_and_returns_204(tmp_path):
    service = FakeService()
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    resp = client.post("/edit/a.m4a", data={
        "name": "New name", "transcript": "New body", "route": "drive",
    })

    # Auto-save persists the fields without submitting/routing the memo.
    assert service.edits == [
        ("a.m4a", {"name": "New name", "transcript": "New body", "route": "drive"})
    ]
    assert service.submitted == []
    assert resp.status_code == 204


def test_audio_serves_file_from_inbox(tmp_path):
    (tmp_path / "a.m4a").write_bytes(b"AUDIODATA")
    client = create_app(FakeService(), inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    resp = client.get("/audio/a.m4a")

    assert resp.status_code == 200
    assert resp.data == b"AUDIODATA"


def test_delete_route_discards_and_returns_204(tmp_path):
    service = FakeService()
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    resp = client.post("/delete/a.m4a")

    assert service.deleted == ["a.m4a"]
    # 204 (no redirect): the trash button removes the row optimistically.
    assert resp.status_code == 204


def test_bin_lists_binned_items(tmp_path):
    service = FakeService(binned=[
        Memo(audio_filename="b.m4a", name="Old note", transcript="bin body",
             status="deleted", processed_at="2026-07-07T03:00"),
    ])
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    resp = client.get("/bin")

    assert resp.status_code == 200
    assert b"Old note" in resp.data
    assert b"bin body" in resp.data
    assert b"b.m4a" in resp.data


def test_restore_route_restores_and_redirects(tmp_path):
    service = FakeService()
    client = create_app(service, inbox_dir=str(tmp_path), bin_dir=str(tmp_path / "bin")).test_client()

    resp = client.post("/restore/b.m4a")

    assert service.restored == ["b.m4a"]
    assert resp.status_code == 302


def test_bin_audio_serves_from_bin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "b.m4a").write_bytes(b"BINAUDIO")
    client = create_app(FakeService(), inbox_dir=str(tmp_path), bin_dir=str(bin_dir)).test_client()

    resp = client.get("/bin-audio/b.m4a")

    assert resp.status_code == 200
    assert resp.data == b"BINAUDIO"
