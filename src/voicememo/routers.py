"""Routers that deliver a submitted memo to Notesnook or Google Drive."""
import html
import re
import shutil
from datetime import datetime
from pathlib import Path

import requests


def _text_to_html(text):
    paragraphs = [html.escape(line.strip()) for line in text.split("\n") if line.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs) or "<p></p>"


def _default_title(timestamp):
    """Name an unnamed memo the way Notesnook names untitled notes ("Note $date$
    $time$"), from an ISO timestamp. Notesnook's Inbox API requires a non-empty
    title, so this always returns one even when the timestamp is missing."""
    try:
        made = datetime.fromisoformat(timestamp)
    except ValueError:
        return "Voice note"
    hour = made.hour % 12 or 12
    meridiem = "AM" if made.hour < 12 else "PM"
    return f"Note {made:%Y-%m-%d} {hour}:{made:%M} {meridiem}"


class NotesnookRouter:
    """Create a note via the Notesnook Inbox API (POST https://inbox.notesnook.com/)."""

    ENDPOINT = "https://inbox.notesnook.com/"

    def __init__(self, api_key, *, source="voicememo", post=requests.post):
        self._api_key = api_key
        self._source = source
        self._post = post

    def route(self, memo):
        response = self._post(
            self.ENDPOINT,
            headers={"Authorization": self._api_key, "Content-Type": "application/json"},
            json={
                "title": memo.name or _default_title(memo.recorded_at or memo.created_at),
                "type": "note",
                "source": self._source,
                "version": 1,
                "content": {"type": "html", "data": _text_to_html(memo.transcript)},
            },
            timeout=30,
        )
        response.raise_for_status()


class Router:
    """Dispatch a memo to the Notesnook or Drive router based on its chosen route."""

    def __init__(self, notesnook, drive=None):
        self._notesnook = notesnook
        self._drive = drive

    def __call__(self, memo):
        if memo.route == "drive":
            if self._drive is not None:
                self._drive.route(memo)
        else:
            self._notesnook.route(memo)


def _today():
    return datetime.now().strftime("%Y_%m_%d")


def _sanitize_filename(name):
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    return cleaned or "untitled"


def _write_docx(path, text):
    from docx import Document

    document = Document()
    for paragraph in text.split("\n"):
        document.add_paragraph(paragraph)
    document.save(str(path))


class DriveMusicRouter:
    """Move a music memo into a dated folder under the Drive base, with an optional doc."""

    def __init__(self, inbox_dir, drive_base, *, today=_today, write_doc=_write_docx, move=shutil.move):
        self._inbox = Path(inbox_dir)
        self._base = Path(drive_base)
        self._today = today
        self._write_doc = write_doc
        self._move = move

    def route(self, memo):
        folder = self._base / f"_{self._today()}_NOT_YET_PROCESSED_MUSIC"
        folder.mkdir(parents=True, exist_ok=True)
        source = self._inbox / memo.audio_filename
        base = _sanitize_filename(memo.name or Path(memo.audio_filename).stem)
        self._move(str(source), str(folder / (base + source.suffix)))
        if memo.transcript.strip():
            self._write_doc(folder / (base + ".docx"), memo.transcript)
