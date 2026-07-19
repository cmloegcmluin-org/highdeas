"""Tests for filing a memo's transcript into Google Drive as a real, native
Google Doc -- via the actual Drive API, authenticated as Douglas's own Google
account rather than a service account (see drive_write.py's module docstring
for why a service account can't own a file in a personal Drive)."""
from highdeas.drive_write import TOKEN_SCOPE, _user_access_token


def test_user_access_token_reads_the_token_file_and_returns_the_access_token():
    calls = []

    class FakeCredentials:
        token = "fake-user-access-token"

        def refresh(self, request):
            calls.append("refreshed")

        @classmethod
        def from_authorized_user_file(cls, path, scopes):
            calls.append((path, scopes))
            return cls()

    token = _user_access_token("token.json", credentials_cls=FakeCredentials)

    assert token == "fake-user-access-token"
    assert calls == [("token.json", [TOKEN_SCOPE]), "refreshed"]


def test_user_access_token_is_blank_without_a_token_file():
    assert _user_access_token("") == ""
