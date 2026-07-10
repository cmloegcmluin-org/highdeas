"""The LAN-facing upload endpoint the iOS app pushes recordings to.

Contract with the phone: multipart POST /upload, field `audio`, header
`Authorization: Bearer <token>`. Any 2xx means the recording is fully in the
inbox (or already known) and the phone may clear it — so a 2xx must never be
sent before the file is safely in place."""
import io

from audio_files import mp4

from highdeas.ingest import recording_key
from highdeas.upload import create_upload_app

TOKEN = "sekrit-token"


def _client(tmp_path, token=TOKEN, **kwargs):
    app = create_upload_app(inbox_dir=tmp_path / "inbox", token=token, **kwargs)
    return app.test_client()


def _post(client, *, token=TOKEN, filename="voice-8.m4a", body=None, field="audio"):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    data = {}
    if filename is not None:
        data[field] = (io.BytesIO(body if body is not None else mp4(1_700_000_000)), filename)
    return client.post("/upload", data=data, headers=headers)


def test_upload_without_a_token_is_rejected(tmp_path):
    response = _post(_client(tmp_path), token=None)

    assert response.status_code == 401
    assert not (tmp_path / "inbox").exists() or not list((tmp_path / "inbox").iterdir())


def test_upload_with_a_wrong_token_is_rejected(tmp_path):
    assert _post(_client(tmp_path), token="wrong").status_code == 401


def test_uploads_are_refused_outright_when_no_token_is_configured(tmp_path):
    # An empty HIGHDEAS_UPLOAD_TOKEN must fail closed, not accept empty Bearers.
    assert _post(_client(tmp_path, token=""), token="").status_code == 401


def test_upload_lands_in_the_inbox_under_its_content_key(tmp_path):
    client = _client(tmp_path)

    response = _post(client, body=mp4(1_700_000_000))

    assert response.status_code == 201
    landed = tmp_path / "inbox" / response.get_json()["stored"]
    assert landed.read_bytes() == mp4(1_700_000_000)
    # Stored under the content key of the name the phone sent, so ingest's
    # re-keying is a no-op and recycled phone filenames can't collide.
    assert landed.name == recording_key(landed, name="voice-8.m4a") == recording_key(landed)


def test_upload_without_an_audio_field_is_rejected(tmp_path):
    assert _post(_client(tmp_path), filename=None).status_code == 400


def test_upload_under_a_different_field_name_is_rejected(tmp_path):
    assert _post(_client(tmp_path), field="file").status_code == 400


def test_upload_with_a_non_audio_suffix_is_rejected_and_leaves_no_file(tmp_path):
    client = _client(tmp_path)

    response = _post(client, filename="notes.txt", body=b"not audio")

    assert response.status_code == 415
    inbox = tmp_path / "inbox"
    assert not inbox.exists() or not list(inbox.iterdir())


def test_upload_strips_client_supplied_path_segments(tmp_path):
    # A filename like ../outside.m4a must land inside the inbox, never beside it.
    client = _client(tmp_path)

    response = _post(client, filename="../outside.m4a")

    assert response.status_code == 201
    stored = response.get_json()["stored"]
    assert "/" not in stored and ".." not in stored
    assert (tmp_path / "inbox" / stored).exists()
    assert not (tmp_path / "outside.m4a").exists()


def test_upload_leaves_nothing_behind_but_the_landed_recording(tmp_path):
    # The staging file must be renamed (not copied) into place, and never
    # linger under an audio suffix ingest would adopt half-written.
    client = _client(tmp_path)

    response = _post(client)

    assert response.status_code == 201
    inbox = tmp_path / "inbox"
    assert [p.name for p in inbox.iterdir()] == [response.get_json()["stored"]]


def test_reuploading_a_recording_still_in_the_inbox_is_acknowledged_not_duplicated(tmp_path):
    # The phone retries until it hears a 2xx; a retry whose first attempt
    # actually landed must be confirmed, not stored twice or errored.
    client = _client(tmp_path)
    first = _post(client)

    again = _post(client)

    assert again.status_code == 200
    assert again.get_json()["stored"] == first.get_json()["stored"]
    assert [p.name for p in (tmp_path / "inbox").iterdir()] == [first.get_json()["stored"]]


def test_a_recording_the_store_already_knows_is_acknowledged_without_writing(tmp_path):
    # A retry can arrive after the memo was processed and its file moved to
    # the bin. The store still knows the key: confirm receipt and drop the
    # bytes, or the inbox gains an orphan file ingest will never adopt.
    client = _client(tmp_path, is_known=lambda key: True)

    response = _post(client)

    assert response.status_code == 200
    inbox = tmp_path / "inbox"
    assert not inbox.exists() or not list(inbox.iterdir())


def test_a_landed_upload_is_announced_and_a_duplicate_is_not(tmp_path):
    received = []
    client = _client(tmp_path, on_received=received.append)

    first = _post(client)
    _post(client)

    assert received == [first.get_json()["stored"]]
