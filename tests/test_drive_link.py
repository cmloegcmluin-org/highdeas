"""Tests for resolving a memo's Drive subfolder to its own Drive link, via the
real Google Drive API — the only way to learn a Drive-assigned folder ID for
anything Drive for Desktop uploads on its own schedule."""
from highdeas.drive_link import (
    TOKEN_SCOPE, DriveFolderLinker, _service_account_token, parent_id_from_folder_url,
)


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class FakeGet:
    def __init__(self, status_code=200, body=None):
        self.calls = []
        self._status_code = status_code
        self._body = body

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self._status_code, self._body)


def test_parent_id_from_folder_url_extracts_the_id_drive_embeds_in_its_share_link():
    url = "https://drive.google.com/drive/folders/1AbCDeFGhIJKlmNOpQRstuVwxYZ01234?usp=sharing"
    assert parent_id_from_folder_url(url) == "1AbCDeFGhIJKlmNOpQRstuVwxYZ01234"


def test_parent_id_from_folder_url_blank_when_theres_no_folder_id():
    assert parent_id_from_folder_url("") == ""
    assert parent_id_from_folder_url(None) == ""
    assert parent_id_from_folder_url("https://drive.google.com/drive/search?q=x") == ""


def test_service_account_token_reads_the_key_file_and_returns_the_access_token():
    calls = []

    class FakeCredentials:
        token = "fake-access-token"

        def refresh(self, request):
            calls.append("refreshed")

        @classmethod
        def from_service_account_file(cls, path, scopes):
            calls.append((path, scopes))
            return cls()

    token = _service_account_token("service-account.json", credentials_cls=FakeCredentials)

    assert token == "fake-access-token"
    assert calls == [("service-account.json", [TOKEN_SCOPE]), "refreshed"]


def test_service_account_token_is_blank_without_a_key_file():
    assert _service_account_token("") == ""


def test_link_for_resolves_the_subfolders_own_drive_link():
    get = FakeGet(body={"files": [{"id": "SUBFOLDER_ID_1"}]})
    linker = DriveFolderLinker("key.json", "PARENT_ID", get=get, token=lambda key: "tok-123")

    link = linker.link_for("_2026_07_17_NOT_YET_PROCESSED_MUSIC")

    assert link == "https://drive.google.com/drive/folders/SUBFOLDER_ID_1"
    url, kwargs = get.calls[0]
    assert url == "https://www.googleapis.com/drive/v3/files"
    assert kwargs["headers"] == {"Authorization": "Bearer tok-123"}
    assert "'PARENT_ID' in parents" in kwargs["params"]["q"]
    assert "name = '_2026_07_17_NOT_YET_PROCESSED_MUSIC'" in kwargs["params"]["q"]
    assert "mimeType = 'application/vnd.google-apps.folder'" in kwargs["params"]["q"]


def test_link_for_blank_when_the_subfolder_hasnt_synced_up_yet():
    # Drive for Desktop uploads on its own schedule; a subfolder just filed to
    # locally may not exist in Drive's cloud yet at the moment the icon is clicked.
    get = FakeGet(body={"files": []})
    linker = DriveFolderLinker("key.json", "PARENT_ID", get=get, token=lambda key: "tok")

    assert linker.link_for("_2026_07_17_NOT_YET_PROCESSED_MUSIC") == ""


def test_link_for_blank_without_a_key_file_or_parent_id():
    assert DriveFolderLinker("", "PARENT_ID", token=lambda key: "tok").link_for("sub") == ""
    assert DriveFolderLinker("key.json", "", token=lambda key: "tok").link_for("sub") == ""


def test_link_for_blank_when_theres_no_subfolder_name():
    linker = DriveFolderLinker("key.json", "PARENT_ID", token=lambda key: "tok")
    assert linker.link_for("") == ""


def test_link_for_blank_when_the_token_cant_be_obtained():
    # A misconfigured or revoked service account must fall back quietly, not 500.
    linker = DriveFolderLinker("key.json", "PARENT_ID", token=lambda key: "")
    assert linker.link_for("_2026_07_17_NOT_YET_PROCESSED_MUSIC") == ""


def test_link_for_blank_when_the_lookup_fails():
    def blowing_up_get(*args, **kwargs):
        raise ConnectionError("offline")

    linker = DriveFolderLinker("key.json", "PARENT_ID", get=blowing_up_get, token=lambda key: "tok")

    assert linker.link_for("_2026_07_17_NOT_YET_PROCESSED_MUSIC") == ""


def test_link_for_escapes_a_quote_in_the_subfolder_name():
    # Defensive: today's subfolder names are always machine-generated dates, but
    # the query must stay well-formed if a name ever contains a literal quote.
    get = FakeGet(body={"files": []})
    linker = DriveFolderLinker("key.json", "PARENT_ID", get=get, token=lambda key: "tok")

    linker.link_for("O'Brien's Folder")

    query = get.calls[0][1]["params"]["q"]
    assert "O\\'Brien\\'s Folder" in query
