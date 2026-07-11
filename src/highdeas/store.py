"""Stores for memo state (transcript, name, route, status).

Two implementations of one contract. `MemoStore` keeps everything in a local
SQLite file — right for a single machine. `FolderStore` keeps one JSON file
per memo in a folder a sync engine (Syncthing) carries between machines —
the no-special-machine store (docs/mac-peer.md): SQLite corrupts when two
writers meet through a sync folder; per-memo files make the unit of conflict
a single memo, and last writer wins."""
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Memo:
    audio_filename: str
    transcript: str = ""
    name: str = ""
    route: str = "notesnook"
    # The Asana task this memo becomes a subtask of when its route is "asana" —
    # a gid from the ASANA_PARENT_TASKS dropdown. Empty means the configured default.
    asana_parent: str = ""
    # The link Asana returned for the task this memo became, so the bin can open it.
    # Empty for other routes and for memos sent before permalinks were stored.
    asana_url: str = ""
    status: str = "pending"
    created_at: str = ""
    recorded_at: str = ""
    processed_at: str = ""
    # Where the user dragged this memo in the inbox. None until they reorder, and
    # again once a memo re-enters the inbox, so unplaced memos fall back to
    # recorded order (see list_pending).
    position: int = None
    # When each transcribed word was spoken, as the JSON the editor reads back:
    # [[startSeconds, word], …]. Empty for memos transcribed before timings existed.
    word_times: str = ""
    # "note" or "group": a group's transcript is a bulleted consolidation of the
    # notes merged into it. Memos stored before this column existed read back as
    # None, which is simply "not a group".
    kind: str = "note"
    # Each merge a group swallowed is walked back on its own, so a group keeps a trail
    # of them, oldest first, as JSON: one entry per merge, holding the notes that merge
    # absorbed and the memo as it read before it took them.
    #   [{"files": […], "kind": …, "name": …, "transcript": …}, …]
    # Empty on a plain note, and on a group folded before the trail existed.
    merges: str = ""


_COLUMNS = [f.name for f in fields(Memo)]
# Position must compare as a number: in a TEXT column SQLite would sort '10' before '2'.
_COLUMN_TYPES = {"position": "INTEGER"}


def _declaration(column):
    return f"{column} {_COLUMN_TYPES.get(column, 'TEXT')}"


def _row_to_memo(row):
    return Memo(**{c: row[c] for c in _COLUMNS})


class MemoStore:
    """Thread-safe: the Flask dev server serves each request in its own thread."""

    def __init__(self, db_path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        columns = ", ".join(_declaration(c) for c in _COLUMNS)
        with self._lock:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS memos ({columns}, PRIMARY KEY (audio_filename))"
            )
            present = {row["name"] for row in self._conn.execute("PRAGMA table_info(memos)")}
            for column in _COLUMNS:
                if column not in present:
                    self._conn.execute(f"ALTER TABLE memos ADD COLUMN {_declaration(column)}")
            self._conn.commit()

    def upsert(self, memo):
        placeholders = ", ".join("?" for _ in _COLUMNS)
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO memos ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                [getattr(memo, c) for c in _COLUMNS],
            )
            self._conn.commit()

    def get(self, audio_filename):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memos WHERE audio_filename = ?", (audio_filename,)
            ).fetchone()
        return _row_to_memo(row) if row is not None else None

    def known_filenames(self):
        with self._lock:
            rows = self._conn.execute("SELECT audio_filename FROM memos").fetchall()
        return {row["audio_filename"] for row in rows}

    def list_pending(self):
        """Every memo still in the inbox, in the order the inbox shows them.

        A memo the user dragged into place leads with its position. Everything else has
        no position and falls back to recording time, then ingest time as a stable
        tiebreak: an untouched inbox reads oldest-to-newest by when each memo was
        recorded, regardless of the order a startup catch-up (which scans the inbox by
        filename) happened to ingest them in. Unplaced memos sort after placed ones, so a
        recording that lands after a reorder joins the end rather than jumping the queue.
        The bin re-sorts its own view by processed_at, so this ordering only shapes the
        inbox."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memos WHERE status = 'pending' "
                "ORDER BY position IS NULL, position, recorded_at, created_at"
            ).fetchall()
        return [_row_to_memo(row) for row in rows]

    def list_retired(self):
        """Every memo that has left the inbox — submitted, trashed, or absorbed into a
        group. Their recordings share the bin, so the bin lists them all; callers that
        care which way a memo left read its status."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM memos WHERE status != 'pending'").fetchall()
        return [_row_to_memo(row) for row in rows]

    def reorder(self, audio_filenames):
        """Pin these memos to the given order, positioning them ahead of the rest."""
        with self._lock:
            self._conn.executemany(
                "UPDATE memos SET position = ? WHERE audio_filename = ?",
                list(enumerate(audio_filenames)),
            )
            self._conn.commit()

    def update(self, audio_filename, **changes):
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with self._lock:
            self._conn.execute(
                f"UPDATE memos SET {assignments} WHERE audio_filename = ?",
                [*changes.values(), audio_filename],
            )
            self._conn.commit()

    def rekey(self, old_filename, new_filename):
        """Move a memo to a new audio_filename (its primary key), keeping the rest."""
        with self._lock:
            self._conn.execute(
                "UPDATE memos SET audio_filename = ? WHERE audio_filename = ?",
                (new_filename, old_filename),
            )
            self._conn.commit()

    def remove(self, audio_filename):
        with self._lock:
            self._conn.execute("DELETE FROM memos WHERE audio_filename = ?", (audio_filename,))
            self._conn.commit()


def _pending_order(memo):
    """The inbox order (see MemoStore.list_pending): dragged memos lead by
    position; the rest follow by recorded time, then ingest time."""
    return (memo.position is None,
            memo.position if memo.position is not None else 0,
            memo.recorded_at, memo.created_at)


class FolderStore:
    """One JSON file per memo, in a folder built to be synced between machines.

    Every write goes to a temp name and renames into place, so no reader — on
    this machine or the other one, mid-sync — ever sees half a memo. Every
    query reads the folder fresh: the other machine may have changed it since
    the last look, and the folder is the source of truth."""

    def __init__(self, state_dir):
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, audio_filename):
        return self._dir / f"{audio_filename}.json"

    def _write(self, memo):
        path = self._path(memo.audio_filename)
        tmp = path.with_name(path.name + ".tmp")  # *.json.tmp: no reader globs it
        tmp.write_text(json.dumps(asdict(memo), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)

    def _read(self, path):
        """The memo in `path`, or None for anything that isn't one of ours:
        a file the sync engine hasn't finished delivering, a foreign JSON, a
        memo from a newer version (its extra fields are dropped, mirroring the
        SQLite store's forward-only column migration), or a sync-conflict copy
        — whose stem no longer matches its content, and whose adoption would
        resurrect the losing write as a phantom twin."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or "audio_filename" not in data:
            return None
        known = {f.name for f in fields(Memo)}
        memo = Memo(**{k: v for k, v in data.items() if k in known})
        if path.name != f"{memo.audio_filename}.json":
            return None
        return memo

    def _all(self):
        return [memo for path in sorted(self._dir.glob("*.json"))
                if (memo := self._read(path)) is not None]

    def upsert(self, memo):
        with self._lock:
            self._write(memo)

    def get(self, audio_filename):
        with self._lock:
            path = self._path(audio_filename)
            return self._read(path) if path.exists() else None

    def known_filenames(self):
        with self._lock:
            return {memo.audio_filename for memo in self._all()}

    def list_pending(self):
        with self._lock:
            pending = [m for m in self._all() if m.status == "pending"]
        return sorted(pending, key=_pending_order)

    def list_retired(self):
        with self._lock:
            return [m for m in self._all() if m.status != "pending"]

    def reorder(self, audio_filenames):
        with self._lock:
            for position, name in enumerate(audio_filenames):
                path = self._path(name)
                memo = self._read(path) if path.exists() else None
                if memo is not None:
                    memo.position = position
                    self._write(memo)

    def update(self, audio_filename, **changes):
        with self._lock:
            path = self._path(audio_filename)
            memo = self._read(path) if path.exists() else None
            if memo is None:
                return
            for key, value in changes.items():
                setattr(memo, key, value)
            self._write(memo)

    def rekey(self, old_filename, new_filename):
        """Move a memo to a new audio_filename, keeping the rest. New file
        lands before the old one goes, so a crash in between duplicates a
        memo (harmless, converges) rather than losing one."""
        with self._lock:
            path = self._path(old_filename)
            memo = self._read(path) if path.exists() else None
            if memo is None:
                return
            memo.audio_filename = new_filename
            self._write(memo)
            path.unlink(missing_ok=True)

    def remove(self, audio_filename):
        with self._lock:
            self._path(audio_filename).unlink(missing_ok=True)
