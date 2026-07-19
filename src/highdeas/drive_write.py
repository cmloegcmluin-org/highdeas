"""File a memo's transcript into Google Drive as a real, native Google Doc --
created through the actual Drive API, not the docx-into-a-locally-mirrored-folder
trick routers.write_docx still falls back to.

This authenticates as Douglas's own Google account (OAuth "user" credentials),
never as the service account drive_link.py reads with. That distinction isn't a
style choice: a service account has no Drive storage quota of its own, and Google
enforces this hard -- it cannot own a newly created file inside a personal
(non-Workspace) "My Drive" at all, confirmed against Google's own error message
for it ("Service Accounts do not have storage quota"), not assumed. Only a real
signed-in user can own a new file, so creating one has to happen as Douglas,
via a one-time browser consent (scripts/authorize_google_docs.py) that leaves a
refresh token behind for every run after.

That token is scoped to drive.file, deliberately the narrowest Drive scope
Google offers: full drive access exists too, but it is a "restricted" scope
that requires an annual third-party security assessment (Google's CASA program)
to use outside of Google's own review -- a paid audit process built for
companies, not a one-person tool. drive.file avoids it, at a real cost this
module is built around: a client holding only drive.file can never see or
write into a folder it did not itself create (confirmed against Google's own
Drive API docs and reports of the exact "insufficient permissions" failure this
would otherwise hit) -- not one the Drive website made, not one Drive for
Desktop synced up from a local folder, even shared Editor. So the folder tree
this files into (HIGHDEAS_DRIVE_DOCS_FOLDER_NAME, dated subfolders beneath it)
is entirely its own, separate from HIGHDEAS_DRIVE_BASE, the folder the audio
copy still goes to (routers.DriveMusicRouter) -- nesting into that one instead
would need either the broader restricted scope (the CASA assessment above) or
Douglas re-granting access through Drive's file picker for every subfolder ever
created, a worse one-time setup than a second folder tree in exchange for."""
import json

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from highdeas.drive_link import _escaped

# The narrowest Drive scope that can create files at all: see the module
# docstring for why this, and not the full (and restricted) drive scope.
TOKEN_SCOPE = "https://www.googleapis.com/auth/drive.file"

_FILES_ENDPOINT = "https://www.googleapis.com/drive/v3/files"
_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/drive/v3/files"


def _user_access_token(token_file, *, credentials_cls=Credentials):
    """A fresh OAuth access token for the Google account authorized into
    `token_file` (the file scripts/authorize_google_docs.py writes after Douglas
    signs in once) -- or "" without one configured. The caller that builds a
    DriveDocFiler is already None in that case (see app._drive_doc_filer), but
    this stays defensive rather than assume it's never reached any other way,
    the same posture drive_link._service_account_token takes."""
    if not token_file:
        return ""
    credentials = credentials_cls.from_authorized_user_file(token_file, scopes=[TOKEN_SCOPE])
    credentials.refresh(Request())
    return credentials.token
