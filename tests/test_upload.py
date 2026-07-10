"""The LAN-facing upload endpoint the iOS app pushes recordings to.

Contract with the phone: multipart POST /upload, field `audio`, header
`Authorization: Bearer <token>`. Any 2xx means the recording is fully in the
inbox (or already known) and the phone may clear it — so a 2xx must never be
sent before the file is safely in place."""
import io
import os
import time

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


def test_the_upload_app_exposes_only_the_upload_route(tmp_path):
    # This app binds 0.0.0.0. Flask's default static route would serve the
    # package's static/ (the inbox UI's JS/CSS) to the whole LAN — the app
    # must carry exactly one route.
    app = create_upload_app(inbox_dir=tmp_path / "inbox", token=TOKEN)

    assert {rule.rule for rule in app.url_map.iter_rules()} == {"/upload"}


def test_windows_hostile_filename_characters_are_neutralized(tmp_path):
    # The production inbox is NTFS: ':' names an alternate data stream (the
    # bytes vanish from directory listings but the 2xx already told the phone
    # to delete), and <>|"?* are invalid outright.
    client = _client(tmp_path)

    response = _post(client, filename="memo<1>:take|?*.m4a")

    assert response.status_code == 201
    stored = response.get_json()["stored"]
    assert not (set('<>:"|?*') & set(stored))
    assert (tmp_path / "inbox" / stored).exists()


def test_an_empty_audio_part_is_rejected_not_stored(tmp_path):
    # A zero-byte "recording" (client-side read failure) would be adopted by
    # ingest and then fail transcription on every refresh, forever. Refuse it;
    # the phone keeps its copy and surfaces the block.
    client = _client(tmp_path)

    response = _post(client, body=b"")

    assert response.status_code == 400
    inbox = tmp_path / "inbox"
    assert not inbox.exists() or not list(inbox.iterdir())


def test_an_oversized_body_is_refused(tmp_path):
    client = _client(tmp_path, max_bytes=1024)

    response = _post(client, body=b"x" * 4096)

    assert response.status_code == 413


def test_the_bytes_are_forced_to_disk_before_the_2xx(tmp_path, monkeypatch):
    # The phone deletes its only copy on 2xx; the OS write-back cache must not
    # be able to take the recording with it in a crash seconds later.
    import highdeas.upload as upload_mod
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(upload_mod.os, "fsync",
                        lambda fd: (synced.append(fd), real_fsync(fd))[1])

    response = _post(_client(tmp_path))

    assert response.status_code == 201
    assert synced


def test_a_failure_after_staging_returns_5xx_and_leaves_no_trace(tmp_path, monkeypatch):
    # A 2xx is a promise; anything that breaks mid-request must answer 5xx
    # (the phone keeps its copy and retries) and leave no partial behind.
    import highdeas.upload as upload_mod

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(upload_mod, "recording_key", boom)
    client = _client(tmp_path)

    response = _post(client)

    assert response.status_code == 500
    assert not list((tmp_path / "inbox").iterdir())


def test_stale_staging_leftovers_are_swept_when_the_app_is_built(tmp_path):
    # A crash mid-save strands an upload-*.part in a folder the user sees
    # (the real inbox is inside iCloud Drive). Ingest rightly ignores them;
    # the next launch clears the old ones. A fresh .part may be a live upload
    # on another thread — it stays.
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    stale = inbox / "upload-deadbeef.part"
    stale.write_bytes(b"x")
    hour_plus_ago = time.time() - 4000
    os.utime(stale, (hour_plus_ago, hour_plus_ago))
    fresh = inbox / "upload-cafe.part"
    fresh.write_bytes(b"x")

    _client(tmp_path)

    assert not stale.exists()
    assert fresh.exists()
