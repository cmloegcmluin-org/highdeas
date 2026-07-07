"""Routers that deliver a submitted memo to Notesnook or Google Drive."""
import html

import requests


def _text_to_html(text):
    paragraphs = [html.escape(line.strip()) for line in text.split("\n") if line.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs) or "<p></p>"


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
                "title": memo.name or "Untitled voice note",
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
