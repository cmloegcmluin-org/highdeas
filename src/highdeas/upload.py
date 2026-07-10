"""LAN-facing upload app: the iOS capture app pushes recordings straight here.

Kept separate from the inbox app on purpose — this one is bound to the LAN, so
it exposes exactly one route. A 2xx tells the phone the recording is safely in
the inbox (or already known) and may be cleared; it is never sent before the
file is fully in place."""
import hmac
import uuid
from pathlib import Path

from flask import Flask, request

from highdeas.ingest import AUDIO_EXTENSIONS, recording_key


def create_upload_app(inbox_dir, token, is_known=None, on_received=None):
    app = Flask(__name__)

    @app.post("/upload")
    def upload():
        if not token or not hmac.compare_digest(_bearer().encode(), token.encode()):
            return ("Missing or bad upload token.", 401)
        sent = request.files.get("audio")
        if sent is None or not sent.filename:
            return ("No audio file in the request.", 400)
        name = Path(sent.filename).name
        if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
            return (f"Not an audio file: {name}", 415)
        inbox = Path(inbox_dir)
        inbox.mkdir(parents=True, exist_ok=True)
        # Stage under a suffix ingest ignores, so a half-written upload can
        # never be adopted, then rename into place — atomic on one filesystem.
        staged = inbox / f"upload-{uuid.uuid4().hex}.part"
        try:
            sent.save(staged)
            key = recording_key(staged, name=name)
            # The phone retries until it hears a 2xx, so a key that already
            # landed — still in the inbox, or processed and known to the store
            # — is confirmed rather than stored again.
            if (inbox / key).exists() or (is_known is not None and is_known(key)):
                return ({"stored": key}, 200)
            staged.replace(inbox / key)
        finally:
            staged.unlink(missing_ok=True)
        if on_received is not None:
            on_received(key)
        return ({"stored": key}, 201)

    return app


def _bearer():
    """The token of an `Authorization: Bearer <token>` header, or ""."""
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    return credentials.strip() if scheme == "Bearer" else ""
