"""Persist a small frozen dataclass to a JSON file, tolerantly.

The window's geometry and the reader's preferences are each a handful of fields
remembered beside the checkout across launches. This is the read-and-write they
share: a missing file, unreadable contents, or a key the dataclass no longer has
all fall back to the dataclass's own defaults — so a file written by an older or
newer build still loads and never stops the app from opening — and the write goes
through a temp file replaced in one step, so a crash mid-write can't leave a
half-written file behind.
"""
import json
from dataclasses import asdict, fields
from pathlib import Path


def load_state(path, cls):
    """The dataclass as last saved at ``path``, or its defaults if nothing usable is saved."""
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cls()
    if not isinstance(saved, dict):
        return cls()
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in saved.items() if k in known})


def save_state(path, state):
    """Write ``state`` to ``path`` as pretty JSON, replacing the file atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    tmp.replace(path)
