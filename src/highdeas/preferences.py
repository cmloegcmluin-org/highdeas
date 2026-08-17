"""Remember the reader's UI choices across launches, on the server.

The desktop window opens the app on a fresh loopback port every launch and runs its
webview in private mode, so a choice kept in the browser's own localStorage is gone
by the next open — a different origin, and a store the webview wipes on close. Kept
here, beside the window's geometry, the Auto-play choice holds on every platform,
whatever the webview does with its own storage.
"""
from dataclasses import dataclass, replace

from highdeas.state_file import load_state, save_state


@dataclass(frozen=True)
class Preferences:
    """The reader's remembered UI choices. Auto-play ships on — a note is opened to
    be heard — until the reader unticks it."""

    autoplay: bool = True


class PreferenceStore:
    """Reads and writes the reader's preferences, one JSON file beside the checkout.

    Read fresh on each call rather than cached: the file is tiny, this is a local
    app, and a value re-read can't go stale behind a write. A store with no path —
    create_app's fallback when nothing is wired in — keeps the shipped defaults and
    persists nothing, the same shape the app's other optional dependencies take.
    """

    def __init__(self, path=None):
        self._path = path

    def load(self):
        return load_state(self._path, Preferences) if self._path else Preferences()

    def set_autoplay(self, enabled):
        if self._path is not None:
            save_state(self._path, replace(self.load(), autoplay=bool(enabled)))
