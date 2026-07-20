"""Resolve a memo's dated Drive subfolder to that subfolder's own Drive link.

Drive for Desktop uploads a locally-filed subfolder to the cloud on its own schedule,
and Drive's website only ever opens a folder by its own opaque Drive-assigned ID —
never by name or path (confirmed against Drive's own docs, not assumed). The only way
to learn that ID is the real Google Drive API, authenticated as a service account:
given the parent folder's ID (parsed out of its own "Copy link" URL) and the
subfolder's name, ask Drive for the one folder matching both and read its id back."""
import re

import requests
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

# Read-only: this only ever looks a folder up by name, never creates or changes anything.
TOKEN_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

_FILES_ENDPOINT = "https://www.googleapis.com/drive/v3/files"
_FOLDER_ID_IN_URL = re.compile(r"/folders/([\w-]+)")


def parent_id_from_folder_url(url):
    """The folder ID Drive embeds in one of its own "Copy link" URLs
    (.../drive/folders/<ID>...), or "" from anything else — blank, None, or a page
    (like a search-results URL) that isn't a folder link at all."""
    match = _FOLDER_ID_IN_URL.search(url or "")
    return match.group(1) if match else ""


def _service_account_token(service_account_file, *, credentials_cls=Credentials):
    """A fresh OAuth access token for the configured service account, or "" without a
    key file. The resolver that builds a DriveFolderLinker is already None in that
    case (see app._drive_link_resolver), but this stays defensive rather than assume
    it's never reached any other way."""
    if not service_account_file:
        return ""
    credentials = credentials_cls.from_service_account_file(service_account_file, scopes=[TOKEN_SCOPE])
    credentials.refresh(Request())
    return credentials.token


def _escaped(value):
    """A subfolder name safe to splice into a Drive API query's single-quoted
    string. Today's subfolder names are always machine-generated dates and never
    contain a quote, but the query must stay well-formed if that ever changes."""
    return value.replace("'", "\\'")


class DriveFolderLinker:
    """Resolves a subfolder's own Drive link by asking the Drive API for the one
    folder named `subfolder_name` inside the configured parent folder."""

    def __init__(self, service_account_file, parent_id, *, get=requests.get, token=_service_account_token):
        self._service_account_file = service_account_file
        self._parent_id = parent_id
        self._get = get
        self._token = token

    def id_for(self, subfolder_name):
        """The Drive-assigned id of the folder named `subfolder_name` directly
        inside the configured parent, or "" when it can't be resolved: not
        configured, the subfolder hasn't synced up to Drive yet, the service
        account's token can't be obtained, or the lookup itself fails. link_for
        wraps this as a clickable URL for the bin's Drive icon; drive_write's
        DriveDocFiler calls this directly, to learn the audio's own dated
        folder id so a native Doc it already filed elsewhere can be moved into
        it (a files.update addParents call takes a bare id, not a URL).

        Every one of the "can't be resolved" cases falls back quietly rather
        than raising, since both callers have their own fallback for it: the
        bin's Drive icon opens the static top-level link instead, and
        DriveDocFiler leaves the doc exactly where it already filed it."""
        if not self._service_account_file or not self._parent_id or not subfolder_name:
            return ""
        try:
            access_token = self._token(self._service_account_file)
        except Exception:  # noqa: BLE001 — a missing/invalid key file must fall back quietly, not 500
            return ""
        if not access_token:
            return ""
        query = (
            f"'{self._parent_id}' in parents and "
            f"name = '{_escaped(subfolder_name)}' and "
            "mimeType = 'application/vnd.google-apps.folder' and "
            "trashed = false"
        )
        try:
            response = self._get(
                _FILES_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"q": query, "fields": "files(id)"},
                timeout=10,
            )
            response.raise_for_status()
            files = response.json().get("files", [])
        except Exception:  # noqa: BLE001 — offline/misconfigured/revoked must fall back quietly, not 500
            return ""
        return files[0]["id"] if files else ""

    def link_for(self, subfolder_name):
        """That subfolder's own Drive link, or "" when it can't be resolved —
        see id_for for the reasons. The bin's Drive icon falls back to the
        top-level folder link in every one of those cases rather than ever
        raising into the request that clicked it."""
        folder_id = self.id_for(subfolder_name)
        return f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else ""
