"""Application service: turn the inbox into reviewable memos and route submissions."""
import shutil
from datetime import datetime
from pathlib import Path

from voicememo.ingest import find_new_recordings
from voicememo.store import Memo


def _no_router(memo):
    """Placeholder until the Notesnook / Drive routers are wired in."""


def _now():
    return datetime.now().isoformat(timespec="seconds")


class ReviewService:
    def __init__(self, *, inbox_dir, store, transcriber, bin_dir,
                 find_new=find_new_recordings, route=_no_router, clock=_now):
        self._inbox_dir = inbox_dir
        self._store = store
        self._transcriber = transcriber
        self._bin_dir = bin_dir
        self._find_new = find_new
        self._route = route
        self._clock = clock

    def refresh(self):
        for path in self._find_new(self._inbox_dir, self._store.known_filenames()):
            self._store.upsert(Memo(
                audio_filename=path.name,
                transcript=self._transcriber.transcribe(path),
                status="pending",
                created_at=self._clock(),
            ))

    def pending(self):
        return self._store.list_by_status("pending")

    def binned(self):
        """Processed/deleted memos whose recording sits in the local bin, newest first."""
        bin_path = Path(self._bin_dir)
        present = {p.name for p in bin_path.iterdir()} if bin_path.exists() else set()
        retired = self._store.list_by_status("processed") + self._store.list_by_status("deleted")
        in_bin = [memo for memo in retired if memo.audio_filename in present]
        return sorted(in_bin, key=lambda memo: memo.processed_at, reverse=True)

    def edit(self, audio_filename, **fields):
        self._store.update(audio_filename, **fields)

    def submit(self, audio_filename):
        self._route(self._store.get(audio_filename))
        self._retire_audio(audio_filename)
        self._store.update(audio_filename, status="processed", processed_at=self._clock())

    def delete(self, audio_filename):
        self._retire_audio(audio_filename)
        self._store.update(audio_filename, status="deleted", processed_at=self._clock())

    def restore(self, audio_filename):
        source = Path(self._bin_dir) / audio_filename
        if source.exists():
            shutil.move(str(source), str(Path(self._inbox_dir) / audio_filename))
        self._store.update(audio_filename, status="pending", processed_at="")

    def _retire_audio(self, audio_filename):
        """Take the recording out of the inbox, unless the route already moved it (Drive)."""
        source = Path(self._inbox_dir) / audio_filename
        if source.exists():
            bin_dir = Path(self._bin_dir)
            bin_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(bin_dir / audio_filename))
