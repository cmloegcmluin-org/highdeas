# voicememo

Turns iPhone voice memos into finished notes with almost no manual work.

## The flow

1. **Capture** — an iOS Shortcut records audio and drops it into iCloud Drive (`VoiceInbox/`), which iCloud for Windows mirrors to this PC. No Voice Memos app, no manual upload, nothing to clean up.
2. **Ingest** — the app watches the inbox folder for new recordings.
3. **Transcribe** — each recording is transcribed locally.
4. **Review** — a local web page lists each memo with its audio, an editable transcript, a name field, and a Notesnook⇄Drive toggle.
5. **Route on submit**
   - **Notesnook** — the transcript becomes a note via the Notesnook Inbox API.
   - **Drive (music)** — the audio moves into a dated `_YYYY_MM_DD_NOT_YET_PROCESSED_MUSIC` folder under "voice memos (top level)", renamed, with one accompanying doc for any spoken supplement.
6. **Archive** — processed memos are kept 90 days for undo/restore, then purged.

## Status

Working review app: capture → ingest → local transcription → a local web page where you play each memo, edit its transcript, name it, pick Notesnook or Drive, and submit. Not yet wired: the actual Notesnook/Drive delivery on submit (routers), undo, and the archive tab.

## Run it

Double-click **`Review Voice Memos.bat`** (or run `.venv/Scripts/python -m voicememo.app`). It opens the review page in your browser. The first open takes ~15s while the transcription model loads; after that it's quick.

## Setup

- Copy `.env.example` to `.env` and fill in your Notesnook Inbox API key (needed later, for the Notesnook router).

## Tests

    .venv/Scripts/python -m pytest
