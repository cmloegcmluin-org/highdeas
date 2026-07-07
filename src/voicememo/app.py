"""Entrypoint: build the real review service and run the local web app."""
import os
import threading
import webbrowser
from pathlib import Path

from voicememo.service import ReviewService
from voicememo.store import MemoStore
from voicememo.transcribe import Transcriber
from voicememo.web import create_app

DEFAULT_INBOX = r"C:\Users\Douglas\iCloudDrive\iCloud~is~workflow~my~workflows\VoiceInbox"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_app():
    inbox_dir = os.environ.get("VOICE_INBOX_DIR", DEFAULT_INBOX)
    db_path = os.environ.get("VOICE_DB", str(PROJECT_ROOT / "memos.db"))
    service = ReviewService(
        inbox_dir=inbox_dir,
        store=MemoStore(db_path),
        transcriber=Transcriber(),
    )
    return create_app(service, inbox_dir=inbox_dir)


def main():
    port = int(os.environ.get("VOICE_PORT", "5000"))
    app = build_app()
    if os.environ.get("VOICE_OPEN_BROWSER", "1") == "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    app.run(port=port)


if __name__ == "__main__":
    main()
