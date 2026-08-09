"""Command line around highdeas.drive_auth: get Douglas's consent once and save the
refresh token drive_write.py reads on every run after.

The flow itself lives in the package (src/highdeas/drive_auth.py), because the app
runs it itself now when a saved token has lapsed. This is the same thing with
arguments, for a first setup or a deliberate redo.

Usage:
    python scripts/authorize_google_docs.py <client_secret.json> <token.json>

<client_secret.json> is the OAuth client downloaded from Google Cloud Console
(APIs & Services -> Credentials -> Create Credentials -> OAuth client ID -> Desktop
app -> Download JSON) -- see README "Google Drive native Doc filing" for the full
one-time Cloud Console setup this depends on. <token.json> is wherever the result
should be saved; that path is what HIGHDEAS_GOOGLE_DOCS_TOKEN_FILE in .env should then
point at.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from highdeas.drive_auth import (  # noqa: E402 -- see sys.path.insert above
    TOKEN_SCOPE, _client_info, authorization_code_from_callback, authorization_url,
    exchange_code_for_tokens, run, save_token,
)

__all__ = [
    "TOKEN_SCOPE", "_client_info", "authorization_code_from_callback",
    "authorization_url", "exchange_code_for_tokens", "run", "save_token", "main",
]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("Usage: python scripts/authorize_google_docs.py <client_secret.json> <token.json>",
              file=sys.stderr)
        raise SystemExit(1)
    client_file, token_file = argv
    if not run(client_file, token_file):
        raise SystemExit(1)
    print("Now put that path in .env as HIGHDEAS_GOOGLE_DOCS_TOKEN_FILE, then restart Highdeas.")


if __name__ == "__main__":
    main()
