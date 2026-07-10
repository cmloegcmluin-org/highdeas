"""LAN-facing upload app: the iOS capture app pushes recordings straight here.

Kept separate from the inbox app on purpose — this one is bound to the LAN, so
it exposes exactly one route (no Flask static route: the package's static/
belongs to the loopback-only inbox UI). A 2xx tells the phone the recording is
safely in the inbox (or already known) and may be cleared; it is never sent
before the file is fully in place."""
import hmac
import os
import re
import time
import uuid
from pathlib import Path

from flask import Flask, request

from highdeas.ingest import AUDIO_EXTENSIONS, recording_key

# NTFS-invalid characters, plus ':' which would silently write an alternate
# data stream, plus control characters. The inbox lives on a Windows PC.
_HOSTILE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# How long a staged .part may sit before the startup sweep treats it as the
# leftover of a crashed request rather than a live upload on another thread.
_STALE_STAGING_SECONDS = 3600


def create_upload_app(inbox_dir, token, is_known=None, on_received=None,
                      max_bytes=1_000_000_000):
    app = Flask(__name__, static_folder=None)
    # One long voice memo is tens of MB; a runaway body should 413, not fill
    # the disk (werkzeug spools one copy to temp and we write another).
    app.config["MAX_CONTENT_LENGTH"] = max_bytes
    _sweep_stale_staging(Path(inbox_dir))

    @app.post("/upload")
    def upload():
        if not token or not hmac.compare_digest(_bearer().encode(), token.encode()):
            return ("Missing or bad upload token.", 401)
        sent = request.files.get("audio")
        if sent is None or not sent.filename:
            return ("No audio file in the request.", 400)
        name = _safe_name(sent.filename)
        if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
            return (f"Not an audio file: {name}", 415)
        inbox = Path(inbox_dir)
        inbox.mkdir(parents=True, exist_ok=True)
        # Stage under a suffix ingest ignores, so a half-written upload can
        # never be adopted, then rename into place — atomic on one filesystem.
        staged = inbox / f"upload-{uuid.uuid4().hex}.part"
        try:
            sent.save(staged)
            if staged.stat().st_size == 0:
                # A zero-byte "recording" would fail transcription on every
                # refresh forever; the phone keeps its copy and shows why.
                return ("The audio file was empty.", 400)
            key = recording_key(staged, name=name)
            # The phone retries until it hears a 2xx, so a key that already
            # landed — still in the inbox, or processed and known to the store
            # — is confirmed rather than stored again.
            if (inbox / key).exists() or (is_known is not None and is_known(key)):
                return ({"stored": key}, 200)
            # The 2xx promises durability: force the bytes out of the OS
            # write-back cache before the rename that makes them visible.
            with open(staged, "ab") as landed_bytes:
                os.fsync(landed_bytes.fileno())
            staged.replace(inbox / key)
        finally:
            staged.unlink(missing_ok=True)
        if on_received is not None:
            on_received(key)
        return ({"stored": key}, 201)

    return app


def _safe_name(filename):
    """The client's filename reduced to something safe to create on NTFS:
    no path segments, no stream/invalid/control characters, no trailing
    dots or spaces (which Windows strips into collisions)."""
    return _HOSTILE.sub("_", Path(filename).name).rstrip(" .")


def _sweep_stale_staging(inbox):
    """Delete .part leftovers of crashed requests. The inbox is a folder the
    user actually looks at (iCloud Drive on the PC), so they must not pile up;
    a *fresh* .part may be a live upload on another thread and stays."""
    if not inbox.is_dir():
        return
    cutoff = time.time() - _STALE_STAGING_SECONDS
    for leftover in inbox.glob("upload-*.part"):
        try:
            if leftover.stat().st_mtime < cutoff:
                leftover.unlink(missing_ok=True)
        except OSError:  # raced with its own request thread; leave it be
            pass


def _bearer():
    """The token of an `Authorization: Bearer <token>` header, or ""."""
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    return credentials.strip() if scheme == "Bearer" else ""
