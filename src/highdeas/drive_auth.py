"""Getting Douglas's own consent for Highdeas to create Drive files as him, and
saving the refresh token every run after reads.

drive_write.py's DriveDocFiler needs an OAuth "user" credential -- his own Google
account, not the service account drive_link.py reads with -- because a service account
has no Drive storage quota of its own, and Google refuses to let it own a newly created
file in a personal Drive (see drive_write.py's module docstring for the confirmed error
message). Getting that credential takes one step nothing can do unattended: him signing
into Google in a real browser and clicking "Allow". Everything around that click is
here -- opening the consent screen, catching Google's redirect on a throwaway local web
server, writing the token in the exact shape google-auth's
Credentials.from_authorized_user_file() reads.

This lives in the package, not in scripts/, because it is no longer only a one-time
chore: the app runs it itself the moment a saved token stops working (see
drive_write.DriveDocFiler's `reauthorize`). scripts/authorize_google_docs.py is the
same thing with a command line around it, for a first setup or a deliberate redo.
"""
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from highdeas.drive_write import TOKEN_SCOPE

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# How long the local callback server waits for Google's redirect before giving up.
# The app starts this by itself now, so the wait must end on its own: Douglas may
# have been nowhere near the browser tab it opened. Long enough to walk over and
# sign in, short enough that a tab closed unnoticed doesn't hold a thread all day.
CONSENT_TIMEOUT_SECONDS = 300


def _client_info(client_file):
    """(client_id, client_secret) out of a Cloud-Console-downloaded OAuth client JSON
    file -- "installed" (a Desktop app client, what the README asks Douglas to
    create) or "web", whichever shape it turns out to hold."""
    data = json.loads(Path(client_file).read_text())
    info = data.get("installed") or data["web"]
    return info["client_id"], info["client_secret"]


def authorization_url(client_id, redirect_uri):
    """Google's own consent-screen URL for `client_id`, sending the approval back to
    `redirect_uri`. access_type=offline and prompt=consent are both load-bearing, not
    decoration: without offline, Google hands back an access token alone -- no refresh
    token to outlive it; without forcing the consent prompt, a *second* authorization
    for the same client+scope+account is silently handed no refresh token at all
    (confirmed against Google's own docs: it issues one only on that first consent) --
    so a redo after a lost or revoked token file would quietly fail without this."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": TOKEN_SCOPE,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{_AUTH_ENDPOINT}?{urlencode(params)}"


def authorization_code_from_callback(path):
    """The `code` Google's redirect carries in its query string, or "" from anything
    else: consent denied (?error=...), or a stray request the local server happens to
    catch (a browser tab's own favicon fetch)."""
    query = parse_qs(urlparse(path).query)
    return query.get("code", [""])[0]


def exchange_code_for_tokens(code, client_id, client_secret, redirect_uri, *, post=requests.post):
    """Trade the one-use authorization code for real tokens -- access, and (see
    authorization_url) refresh -- at Google's own token endpoint."""
    response = post(_TOKEN_ENDPOINT, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    response.raise_for_status()
    return response.json()


def save_token(token_file, client_id, client_secret, refresh_token):
    """Write the "authorized_user" shape google-auth's own
    Credentials.from_authorized_user_file() reads back -- what drive_write.py's
    DriveDocFiler authenticates with on every run after this one."""
    Path(token_file).write_text(json.dumps({
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }))


class _CallbackHandler(BaseHTTPRequestHandler):
    """Answers exactly one request -- Google's redirect back from the consent screen
    -- with a plain human-readable page, and stashes the authorization code it carried
    onto the server itself, so run() can read it back the moment handle_request()
    returns."""

    def do_GET(self):
        self.server.authorization_code = authorization_code_from_callback(self.path)
        ok = bool(self.server.authorization_code)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        message = ("Highdeas is authorized. You can close this tab." if ok else
                   "Authorization was not completed (consent cancelled?). You can close this tab.")
        self.wfile.write(message.encode())

    def log_message(self, format, *args):
        pass  # a console full of "GET / 200" for a single local hit tells Douglas nothing


def _make_server():
    """A throwaway local HTTP server, on whatever port the OS hands out (":0") --
    Google's own loopback-redirect rules for a Desktop app client allow any port on
    127.0.0.1 without pre-registering it, so nothing here needs a fixed one. Its
    timeout is what lets an unanswered consent end by itself."""
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.authorization_code = None
    server.timeout = CONSENT_TIMEOUT_SECONDS
    return server


def run(client_file, token_file, *, open_browser=webbrowser.open, make_server=_make_server,
        exchange=exchange_code_for_tokens, say=print):
    """Walk Douglas through consenting once, and save the refresh token that leaves
    behind. Returns True on success, False (never a raised exception, so this is safe
    to run from a plain double-click, and safe for the app to run on a background
    thread) for anything that stops it short: consent cancelled, the tab closed, the
    wait timed out, or Google declining to hand back a refresh token (see
    authorization_url for when that happens)."""
    try:
        client_id, client_secret = _client_info(client_file)
    except (OSError, ValueError, KeyError):
        say(f"Couldn't read the OAuth client file: {client_file}")
        return False
    server = make_server()
    try:
        host, port = server.server_address
        redirect_uri = f"http://{host}:{port}/"
        url = authorization_url(client_id, redirect_uri)
        say("Opening your browser to sign in to Google and authorize Highdeas...")
        say(f"(If nothing opens, paste this into a browser yourself: {url})")
        open_browser(url)
        server.handle_request()
        code = server.authorization_code
        if not code:
            say("No authorization received -- consent was cancelled, or the tab was closed.")
            return False
        tokens = exchange(code, client_id, client_secret, redirect_uri)
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            say("Google didn't send back a refresh token. Try again -- if it still "
                "doesn't, revoke Highdeas's access at "
                "https://myaccount.google.com/permissions first, then retry.")
            return False
        save_token(token_file, client_id, client_secret, refresh_token)
        say(f"Saved {token_file}.")
        return True
    except Exception as exc:  # noqa: BLE001 — a background caller must never see this raise
        say(f"Authorization failed: {exc}")
        return False
    finally:
        server.server_close()
