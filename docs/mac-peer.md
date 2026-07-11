# No-special-machine Highdeas — Mac peer kickoff

Written 2026-07-10, in session with Douglas on the MacBook, immediately after the
iOS capture app shipped (see `docs/ios-app-handoff.md` for that story). Decisions
below were made with him — don't relitigate them; open questions are marked.

## Mission

Neither machine is special. The Windows PC and this MacBook each run the full
Highdeas app — ingest, transcription, inbox UI, routing — against **one shared
store**, and the iPhone app delivers to whichever machine answers. Same memo list
on both desks; act on a memo wherever you're sitting.

## Decisions (settled with Douglas, 2026-07-10)

1. **Sync engine: Syncthing.** Peer-to-peer folder sync on both machines —
   seconds-fast, no cloud middleman, pairs with Tailscale for syncing away from
   home. Explicitly NOT iCloud for the shared store: its Windows leg is the
   sometimes-hours-late link the iOS app was built to eliminate.
2. **Concurrency: both apps open at once must be safe.** State becomes per-memo
   files written atomically (last-writer-wins per memo); SQLite shrinks to a
   local, rebuildable cache — never the source of truth, never synced.
3. **Delivery order: Mac app standalone first.** Highdeas launches and fully
   works on the Mac against a local scratch inbox before any storage refactor.
   The phone keeps pointing only at the PC until the shared store exists, so
   memos never scatter across machines.

## Phases

1. **Mac standalone** — the app runs on macOS: native window (pywebview Cocoa),
   platform-aware defaults (paths, Chrome launcher), window-geometry tracking
   without winforms assumptions (`window_state.py` reads
   `window.native.WindowState`, a .NET-ism), a launch affordance. Transcription
   already proven on this Mac (model cached, ffmpeg via imageio-ffmpeg).
2. **Shared store** — the kernel. Per-memo sidecar state files (transcript,
   word times, name, status, route, timestamps) beside the audio in the synced
   folder; atomic tmp+rename writes; last-writer-wins; the DB becomes a local
   index rebuilt from the folder. Adoption stays content-keyed, which already
   makes cross-machine double-ingest converge. Design the bin as part of this.
3. **Syncthing rollout** — install on both machines, share the folder, move
   inbox+bin+state into it, point both apps there.
4. **Phone: multi-peer push + Tailscale** — the iOS app takes a list of server
   URLs and pushes to whichever answers first (the endpoint's content-key dedupe
   already makes double-delivery harmless — verified). Tailscale on phone + both
   machines; the app's ATS currently allows plain HTTP to local addresses only,
   so scope an exception to `ts.net` hostnames (or serve HTTPS via
   `tailscale cert`). Same `HIGHDEAS_UPLOAD_TOKEN` on both machines.

## Hazards, named early

- **SQLite in a synced folder corrupts.** That's why it becomes a cache. No
  synced file may ever be written in place — tmp + rename only.
- **Sync conflicts**: Syncthing renames the loser to a `.sync-conflict-*` file
  rather than merging. Per-memo granularity makes conflicts rare and small, but
  ingest must ignore (or better, surface) conflict files rather than adopt them
  as new recordings.
- **Audio syncing in ahead of its state file** — sharper than first thought:
  the receiving machine would adopt the already-keyed audio as a brand-new
  memo, and its default re-transcription then *wins the sync conflict* over
  the rich, possibly-edited memo about to arrive. Guarded (2026-07-11): an
  already-keyed recording unknown to the store waits `sync_settle_scans`
  scans (~a minute) for its state before being adopted anyway — the fallback
  covers crash orphans; uploads the local listener lands are exempt via
  `refresh(adopt_now=...)`, so a phone push never waits. Plain double-ingest
  of a genuinely raw recording still just converges by content key.
- **Windows paths in defaults** (`DEFAULT_INBOX`, `DEFAULT_CHROME`,
  `DEFAULT_DRIVE_BASE` in `app.py`) — platform-gate them; `.env` carries the
  real values on each machine.
- **Drive routing is PC-only today** (`G:\My Drive\...`). On the Mac, Drive for
  Desktop has a different mount; routing config is per-machine (`.env`), which is
  fine — it is one of the few things that legitimately differs by machine.

## Working agreements (unchanged)

Worktree per task; strict red-green-refactor TDD on the Python side; whole suite
green (zero failures, errors, skips) before every commit; small single-purpose
commits; keep `.env.example`, the README config table, and `pyproject.toml` in
sync with what the code reads. `main` moves fast — rebase, never reset.
