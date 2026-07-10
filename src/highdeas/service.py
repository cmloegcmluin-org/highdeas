"""Application service: turn inbox recordings into memos and route submissions.

The inbox is the app's main view — the list of pending memos awaiting a Notesnook
or Drive decision; the bin holds what's been retired."""
import json
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

from highdeas.ingest import find_new_recordings, recording_key, recording_time
from highdeas.store import Memo


def _no_router(memo):
    """Placeholder until the Notesnook / Drive routers are wired in."""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _word_times(words):
    """The wire format the editor reads to highlight along with the audio."""
    return json.dumps([[word.start, word.text] for word in words], separators=(",", ":"))


def _merges(memo):
    """The trail of merges a group has swallowed, oldest first."""
    return json.loads(memo.merges) if memo.merges else []


def _trail(steps):
    """The trail as the store holds it. An empty one is empty, not the string "[]"."""
    return json.dumps(steps) if steps else ""


def _step(target, absorbed):
    """One merge: what it took in, and the memo as it read before it took them."""
    return {"files": [memo.audio_filename for memo in absorbed],
            "kind": target.kind or "note", "name": target.name,
            "transcript": target.transcript}


def _bullet(memo):
    """One consolidated note as a bullet: its name, colon, then its transcript."""
    text = memo.transcript.strip()
    name = memo.name.strip()
    if name and text:
        return f"- {name}: {text}"
    return f"- {name or text}"


class InboxService:
    def __init__(self, *, inbox_dir, store, transcriber, bin_dir,
                 find_new=find_new_recordings, route=_no_router, clock=_now,
                 recorded_time=recording_time):
        self._inbox_dir = inbox_dir
        self._store = store
        self._transcriber = transcriber
        self._bin_dir = bin_dir
        self._find_new = find_new
        self._route = route
        self._clock = clock
        self._recorded_time = recorded_time
        self._refresh_lock = threading.Lock()

    def refresh(self):
        """Ingest and transcribe any waiting recordings, skipping when a refresh is
        already running. The app's own scan, the client poll, and a second browser
        tab can all land here at once; letting two scans race on the same inbox would
        transcribe a recording twice, or crash renaming a file the other just moved.
        The in-flight scan is already ingesting them, so the skipped caller loses
        nothing — its next poll sees whatever landed."""
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._ingest_waiting_recordings()
        finally:
            self._refresh_lock.release()

    def _ingest_waiting_recordings(self):
        self.purge_expired()
        # A pending memo's audio already lives in the inbox under its own name, so
        # never re-ingest it. find_new keys by content: a memo stored under a raw
        # (pre-content-key) name has a content key that differs from its filename,
        # so find_new would mistake it for a brand-new recording and re-transcribe
        # it — hanging "Back to inbox" (or 500ing) and spawning a duplicate row.
        # Restore now re-keys incoming files, but a legacy raw-named memo left
        # sitting pending in the inbox never passes through restore; guard it here.
        pending = {memo.audio_filename for memo in self._store.list_pending()}
        for recording in self._find_new(self._inbox_dir, self._store.known_filenames()):
            if recording.source.name in pending:
                continue
            try:
                adopted = self._adopt(recording)
                spoken = self._transcriber.transcribe(adopted)
                self._store.upsert(Memo(
                    audio_filename=recording.name,
                    transcript=spoken.text,
                    word_times=_word_times(spoken.words),
                    status="pending",
                    created_at=self._clock(),
                    recorded_at=self._recorded_time(adopted),
                ))
            except Exception as exc:  # noqa: BLE001 — one bad recording must not strand the rest
                # A single unreadable or half-downloaded recording used to abort the whole
                # scan, hiding every recording sorted after it until that one file finally
                # decoded. Skip it and press on; the next refresh retries it (its content
                # key still isn't in the store, so nothing is lost).
                print(f"Highdeas: skipping {recording.name} this pass ({exc}).")

    def pending(self):
        return self._store.list_pending()

    def has_incoming(self):
        """True when the inbox holds recordings not yet in the store, so a freshly
        opened page can say "Transcribing…" rather than "Your inbox is empty" while the
        background scan works through them. A cheap directory scan — no model, no
        decoding, and nothing pulled down from iCloud — so it's safe on the request path."""
        return bool(self._find_new(self._inbox_dir, self._store.known_filenames()))

    def binned(self):
        """Retired memos whose recording sits in the local bin, newest first."""
        bin_path = Path(self._bin_dir)
        present = {p.name for p in bin_path.iterdir()} if bin_path.exists() else set()
        in_bin = [memo for memo in self._store.list_retired() if memo.audio_filename in present]
        return sorted(in_bin, key=lambda memo: memo.processed_at, reverse=True)

    def get(self, audio_filename):
        return self._store.get(audio_filename)

    def edit(self, audio_filename, **fields):
        self._store.update(audio_filename, **fields)

    def reorder(self, audio_filenames):
        """Fix the inbox to the order the user dragged its rows into."""
        self._store.reorder(audio_filenames)

    def group(self, audio_filenames):
        """Consolidate the named pending notes into a single group memo.

        The notes become bullets, in inbox order rather than the order they were
        picked. An already-grouped note among them is the survivor — the others fold
        into its existing bullets — otherwise the topmost note is promoted to a group
        and its own name and transcript become the first bullet, leaving the group
        free to be titled. The absorbed notes retire to the bin, still restorable.

        The merge joins the group's trail, so it can be walked back on its own later."""
        chosen = [m for m in self.pending() if m.audio_filename in set(audio_filenames)]
        if len(chosen) < 2:
            raise ValueError("Grouping needs at least two notes still in the inbox.")
        groups = [memo for memo in chosen if memo.kind == "group"]
        if len(groups) > 1:
            raise ValueError("Two groups have no obvious survivor; merge into one at a time.")
        target = groups[0] if groups else chosen[0]
        absorbed = [memo for memo in chosen if memo is not target]
        # A note promoted to a group starts as a group holding one bullet: its own.
        head = target.transcript.rstrip() if target.kind == "group" else _bullet(target)
        self._store.update(
            target.audio_filename,
            transcript="\n".join([head, *(_bullet(memo) for memo in absorbed)]),
            kind="group",
            name=target.name if target.kind == "group" else "",
            merges=_trail(_merges(target) + [_step(target, absorbed)]),
        )
        for memo in absorbed:
            self._retire(memo.audio_filename, "grouped")
        return self._store.get(target.audio_filename)

    def unmerge(self, audio_filename):
        """Walk back the last merge this group swallowed, and only that one.

        The notes that merge took in return to the inbox with their own name, transcript,
        and recording, in the place each held, and the group reads as it did before it —
        which, for the merge that made the group, is a plain note again. Bullets typed
        into the group since are let go: this is the merge coming undone, not the bullets
        being unpicked.

        A group folded before the trail existed has no merge to walk back, so it only
        stops being a group, keeping the bullets it is holding rather than emptying
        itself. The notes it ate stay in the bin, restorable one at a time."""
        group = self._store.get(audio_filename)
        if group is None or group.kind != "group":
            raise ValueError("Only a group can have a merge walked back.")
        trail = _merges(group)
        if not trail:
            self._store.update(audio_filename, kind="note")
            return
        step = trail.pop()
        for filename in step["files"]:
            self._unretire(filename)
        self._store.update(audio_filename, kind=step["kind"], name=step["name"],
                           transcript=step["transcript"], merges=_trail(trail))

    def ungroup(self, audio_filename):
        """Break a group all the way back into the separate notes it was folded from."""
        group = self._store.get(audio_filename)
        if group is None or group.kind != "group":
            raise ValueError("Only a group can be broken back up into notes.")
        while self._store.get(audio_filename).kind == "group":
            self.unmerge(audio_filename)

    def submit(self, audio_filename):
        outcome = self._route(self._store.get(audio_filename)) or {}
        self._retire(audio_filename, "processed", **outcome)

    def delete(self, audio_filename):
        self._retire(audio_filename, "deleted")

    def restore(self, audio_filename):
        """Bring a binned recording back into the inbox as a pending memo.

        It rejoins the end of the list rather than the slot it once held, since the
        inbox it left may have been rearranged since.

        Realign the memo and its file with the recording's content key on the way
        in: a memo retired before content-keying is stored under its raw inbox
        name, and refresh() would then re-key the restored audio and adopt it as a
        second, brand-new pending memo — the restored item showed up twice."""
        landed = Path(self._inbox_dir) / audio_filename
        source = Path(self._bin_dir) / audio_filename
        if source.exists():
            shutil.move(str(source), str(landed))
        key = recording_key(landed) if landed.exists() else audio_filename
        if key != audio_filename:
            landed.replace(Path(self._inbox_dir) / key)
            if self._store.get(key) is None:
                self._store.rekey(audio_filename, key)
            else:
                # A pre-fix restore already spawned this recording's keyed twin;
                # drop the raw duplicate and converge onto the keyed memo.
                self._store.remove(audio_filename)
        self._store.update(key, status="pending", processed_at="", position=None)

    def purge(self, audio_filename):
        """Permanently remove a single binned recording: its audio and its record."""
        audio = Path(self._bin_dir) / audio_filename
        if audio.exists():
            audio.unlink()
        self._store.remove(audio_filename)

    def empty_bin(self):
        """Permanently remove every recording currently in the bin."""
        for memo in self.binned():
            self.purge(memo.audio_filename)

    def restore_all(self):
        """Return every binned recording to the inbox as a pending memo."""
        for memo in self.binned():
            self.restore(memo.audio_filename)

    def purge_expired(self, *, retention_days=90):
        """Forget bin items older than the retention window: delete the audio and the record."""
        cutoff = datetime.fromisoformat(self._clock()) - timedelta(days=retention_days)
        bin_dir = Path(self._bin_dir)
        for memo in self._store.list_retired():
            if memo.processed_at and datetime.fromisoformat(memo.processed_at) < cutoff:
                audio = bin_dir / memo.audio_filename
                if audio.exists():
                    audio.unlink()
                self._store.remove(memo.audio_filename)

    def _adopt(self, recording):
        """Rename a freshly-arrived recording to its content-unique name so a
        recycled inbox filename can't collide with a past recording — in the
        store now, or in the bin once it's retired. Returns its new path."""
        target = Path(self._inbox_dir) / recording.name
        source = Path(recording.source)
        if source != target:
            source.replace(target)
        return target

    def _retire(self, audio_filename, status, **fields):
        """Take a memo out of the inbox: its recording moves to the bin and it stops
        being pending. Submitting, trashing, and grouping differ only in the status
        they leave behind, which the bin reads back as where the memo went. Extra
        fields about how it left (e.g. Asana's task link) ride the same update.

        No route touches the recording in the inbox (Notesnook and Asana never see
        the file, Drive copies it), so it lands in the bin either way; guard in
        case it's somehow already gone."""
        source = Path(self._inbox_dir) / audio_filename
        if source.exists():
            bin_dir = Path(self._bin_dir)
            bin_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(bin_dir / audio_filename))
        self._store.update(audio_filename, status=status, processed_at=self._clock(), **fields)

    def _unretire(self, audio_filename):
        """Put a memo back in the inbox where it was retired from, keeping the place it
        held. It was keyed by content on the way in, so its recording needs no re-keying
        on the way back — guard only in case the recording is no longer in the bin."""
        source = Path(self._bin_dir) / audio_filename
        if source.exists():
            shutil.move(str(source), str(Path(self._inbox_dir) / audio_filename))
        self._store.update(audio_filename, status="pending", processed_at="")
