"""One-time script that gets Douglas's own consent for Highdeas to create Drive files
as him, and saves the refresh token drive_write.py reads on every run after this one.

drive_write.py's DriveDocFiler needs an OAuth "user" credential -- Douglas's own Google
account, not the service account drive_link.py reads with -- because a service account
has no Drive storage quota of its own, and Google refuses to let it own a newly created
file in a personal Drive (see drive_write.py's module docstring for the confirmed error
message). Getting that credential at all takes one interactive step a script can't do
unattended: Douglas signing into Google in a real browser and clicking "Allow". This
script is only that step -- run once (or again if the saved token is ever lost or
revoked) -- opening the consent screen, catching Google's redirect on a throwaway local
web server, and writing what it hands back to a token file in the exact shape
google-auth's Credentials.from_authorized_user_file() reads, so nothing after this run
ever needs the browser again.

Usage:
    python scripts/authorize_google_docs.py <client_secret.json> <token.json>

<client_secret.json> is the OAuth client downloaded from Google Cloud Console
(APIs & Services -> Credentials -> Create Credentials -> OAuth client ID -> Desktop
app -> Download JSON) -- see README "Google Drive native Doc filing" for the full
one-time Cloud Console setup this depends on. <token.json> is wherever the result
should be saved; that path is what HIGHDEAS_GOOGLE_DOCS_TOKEN_FILE in .env should then
point at.
"""
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highdeas.drive_write import TOKEN_SCOPE  # noqa: E402 -- see sys.path.insert above

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def _client_info(client_file):
    """(client_id, client_secret) out of a Cloud-Console-downloaded OAuth client JSON
    file -- "installed" (a Desktop app client, what this script asks Douglas to
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
    127.0.0.1 without pre-registering it, so nothing here needs a fixed one."""
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.authorization_code = None
    return server


def run(client_file, token_file, *, open_browser=webbrowser.open, make_server=_make_server,
        exchange=exchange_code_for_tokens):
    """Walk Douglas through consenting once, and save the refresh token that leaves
    behind. Returns True on success, False (never a raised exception, so this is safe
    to run from a plain double-click) for anything that stops it short: consent
    cancelled, the tab closed, or Google declining to hand back a refresh token (see
    authorization_url for when that happens)."""
    client_id, client_secret = _client_info(client_file)
    server = make_server()
    try:
        host, port = server.server_address
        redirect_uri = f"http://{host}:{port}/"
        url = authorization_url(client_id, redirect_uri)
        print("Opening your browser to sign in to Google and authorize Highdeas...")
        print(f"(If nothing opens, paste this into a browser yourself: {url})")
        open_browser(url)
        server.handle_request()
        code = server.authorization_code
        if not code:
            print("No authorization received -- consent was cancelled, or the tab was closed.")
            return False
        tokens = exchange(code, client_id, client_secret, redirect_uri)
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            print("Google didn't send back a refresh token. Try running this again -- if it "
                  "still doesn't, revoke Highdeas's access at "
                  "https://myaccount.google.com/permissions first, then retry.")
            return False
        save_token(token_file, client_id, client_secret, refresh_token)
        print(f"Saved {token_file}.")
        print("Now put that path in .env as HIGHDEAS_GOOGLE_DOCS_TOKEN_FILE, then restart Highdeas.")
        return True
    finally:
        server.server_close()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("Usage: python scripts/authorize_google_docs.py <client_secret.json> <token.json>",
              file=sys.stderr)
        raise SystemExit(1)
    client_file, token_file = argv
    try:
        ok = run(client_file, token_file)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Couldn't complete authorization: {exc}\n"
              f"Is {client_file!r} the OAuth client JSON downloaded from Cloud Console?",
              file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
