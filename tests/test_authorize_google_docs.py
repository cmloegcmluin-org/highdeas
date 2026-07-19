"""Tests for the one-time script that gets Douglas's own consent for Highdeas
to create Drive files as him, and saves the refresh token every run after this
one reads (see drive_write.py for why this has to be his account, not a
service account)."""
import json

import pytest

from authorize_google_docs import (
    TOKEN_SCOPE,
    _client_info,
    authorization_code_from_callback,
    authorization_url,
    exchange_code_for_tokens,
    run,
    save_token,
)


def test_client_info_reads_an_installed_app_client_file(tmp_path):
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"installed": {"client_id": "ID", "client_secret": "SECRET"}}))

    assert _client_info(client_file) == ("ID", "SECRET")


def test_client_info_reads_a_web_client_file_too(tmp_path):
    # Cloud Console can hand back either shape depending on the client type
    # picked; a "Desktop app" client is "installed", but this shouldn't care.
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"web": {"client_id": "ID", "client_secret": "SECRET"}}))

    assert _client_info(client_file) == ("ID", "SECRET")


def test_authorization_url_carries_the_client_id_scope_and_redirect_uri():
    url = authorization_url("CLIENT_ID", "http://127.0.0.1:54321/")

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=CLIENT_ID" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A54321%2F" in url
    assert f"scope={TOKEN_SCOPE.replace(':', '%3A').replace('/', '%2F')}" in url
    assert "response_type=code" in url
    # Both are required for Google to hand back a refresh token at all, and to hand
    # back a NEW one on a second consent rather than none (see run()'s docstring).
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_authorization_code_from_callback_extracts_the_code():
    assert authorization_code_from_callback("/?code=ABC123&scope=x") == "ABC123"


def test_authorization_code_from_callback_blank_when_consent_was_cancelled():
    assert authorization_code_from_callback("/?error=access_denied") == ""


def test_authorization_code_from_callback_blank_on_an_unrelated_request():
    assert authorization_code_from_callback("/favicon.ico") == ""


def test_exchange_code_for_tokens_posts_the_token_request():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "at", "refresh_token": "rt"}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    tokens = exchange_code_for_tokens("CODE", "CLIENT_ID", "SECRET", "http://127.0.0.1:1/",
                                      post=fake_post)

    assert tokens == {"access_token": "at", "refresh_token": "rt"}
    url, kwargs = calls[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert kwargs["data"] == {
        "code": "CODE",
        "client_id": "CLIENT_ID",
        "client_secret": "SECRET",
        "redirect_uri": "http://127.0.0.1:1/",
        "grant_type": "authorization_code",
    }


def test_save_token_writes_the_authorized_user_shape_google_auth_reads_back(tmp_path):
    token_file = tmp_path / "token.json"

    save_token(token_file, "CLIENT_ID", "SECRET", "REFRESH_TOKEN")

    assert json.loads(token_file.read_text()) == {
        "type": "authorized_user",
        "client_id": "CLIENT_ID",
        "client_secret": "SECRET",
        "refresh_token": "REFRESH_TOKEN",
    }


class FakeServer:
    """Stands in for the real localhost HTTPServer run() waits on: handle_request()
    normally blocks until Google's redirect arrives and the handler stashes the code
    it carried onto the server -- faked here as an instant, canned answer."""

    def __init__(self, code, port=54321):
        self.server_address = ("127.0.0.1", port)
        self._code = code
        self.authorization_code = None
        self.closed = False

    def handle_request(self):
        self.authorization_code = self._code

    def server_close(self):
        self.closed = True


def test_run_happy_path_saves_the_token_and_reports_success(tmp_path, capsys):
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"installed": {"client_id": "ID", "client_secret": "SECRET"}}))
    token_file = tmp_path / "token.json"
    opened = []
    server = FakeServer("AUTH_CODE", port=54321)

    ok = run(client_file, token_file,
             open_browser=opened.append,
             make_server=lambda: server,
             exchange=lambda *a, **k: {"refresh_token": "RT"})

    assert ok is True
    assert json.loads(token_file.read_text())["refresh_token"] == "RT"
    assert "54321" in opened[0]  # the dynamically-bound port made it into the auth URL
    assert server.closed is True


def test_run_fails_without_crashing_when_consent_is_cancelled(tmp_path, capsys):
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"installed": {"client_id": "ID", "client_secret": "SECRET"}}))
    token_file = tmp_path / "token.json"
    server = FakeServer("")  # no ?code= -- Douglas cancelled, or closed the tab

    ok = run(client_file, token_file, open_browser=lambda url: None, make_server=lambda: server,
             exchange=lambda *a, **k: pytest.fail("must not exchange a code that never arrived"))

    assert ok is False
    assert not token_file.exists()


def test_run_fails_without_crashing_when_google_sends_no_refresh_token(tmp_path):
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"installed": {"client_id": "ID", "client_secret": "SECRET"}}))
    token_file = tmp_path / "token.json"
    server = FakeServer("AUTH_CODE")

    ok = run(client_file, token_file, open_browser=lambda url: None, make_server=lambda: server,
             exchange=lambda *a, **k: {"access_token": "at"})  # no refresh_token

    assert ok is False
    assert not token_file.exists()
