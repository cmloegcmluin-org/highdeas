# iOS capture app — handoff

Written 2026-07-10 in a Claude Code session with Douglas on the Windows PC, as the
kickoff brief for a Claude Code session on his Mac. The decisions below were made with
him — don't relitigate them — but do settle the one open question before writing code.

## Mission

Replace the capture leg of Highdeas — an iOS Shortcut saving into iCloud Drive, mirrored
to the PC by iCloud for Windows, sometimes hours late — with a native iOS app that
records and pushes each memo straight to the Highdeas server over HTTP. The Windows PC
stays the brain: ingest, transcription, the inbox UI, and routing to Notesnook/Drive
don't move.

v1 features, agreed with Douglas:

- **Record**, continuing while the screen is locked (`UIBackgroundModes: audio`).
- **A list of recordings still on the phone**, each playable with a **scrub** slider.
- **Push** to the server with a retry queue. A recording is cleared from the phone only
  after the server confirms receipt — same principle as the inbox's "keep notes in the
  inbox unless the server confirms the submit." The row outlives its file by eight
  seconds, marked "Delivered" (`DeliveryReceipts`): the confirmation only comes once the
  bytes are on the other machine's disk, so nothing was ever at risk when the row
  vanished with the file — but a thought disappearing off the screen is a fright whatever
  the truth behind it, and until the desk caught up the note was visible nowhere at all.
  Eight is measured: the desk can *list* the recording within ten milliseconds of the 2xx
  (the upload renames into the inbox before answering, and `/pending` counts it with a
  directory scan), but an open page only asks every five seconds, so the wait is the
  looking. Eight is that poll plus three seconds of overlap — both screens showing the
  note at once, which is the only shape with no gap in it. **The phone does not
  self-update**: the desktops pull from `main`, but a new iOS build reaches the phone
  only by running `ios/resign.sh` with it plugged in.
- ~~**Append** more audio to an existing recording~~ — **cut at kickoff** (see the
  settled question below); a later addition is just a new memo, grouped in the inbox.

Out of scope for v1: on-phone transcription, routing to Notesnook/Drive from the phone,
transcript editing, anything multi-user, App Store / TestFlight distribution.

## Open question — SETTLED with Douglas, 2026-07-10

Auto-push vs. append: **auto-push immediately, and append is eliminated from v1.**
Every recording pushes the moment it stops; the on-phone list is effectively the retry
queue (recordings linger only while unsent). A thought that arrives later becomes its
own memo and is grouped in the PC inbox. This drops the `AVMutableComposition` stitch
work — and with it the post-export creation-time concern — from the app entirely.

## Decisions already made

- **Distribution: free Apple ID ("Personal Team") signing via Xcode.** Douglas chose the
  free weekly-re-sign route over the $99/yr Developer Program. Consequences: installs
  expire after 7 days, so make the weekly refresh one action (Run in Xcode, or script
  `xcodebuild` + `xcrun devicectl device install app`); at most 3 sideloaded apps; the
  iPhone needs Developer Mode enabled once (Settings → Privacy & Security) and the
  certificate trusted once (Settings → General → VPN & Device Management). Background
  audio is an Info.plist key, not a gated entitlement — it works under free signing, and
  nothing in this app needs the entitlements free accounts lack.
- **The app lives in this repo** under `ios/` — SwiftUI, one small Xcode project. Server
  work stays in `src/highdeas/`. One repo, so the upload contract and its client evolve
  in the same commits.
- **Audio format: AAC `.m4a`**, like the Shortcut produces today (ingest facts below).

## Orientation — what exists today

Read the README first. The pipeline: iOS Shortcut records → file lands in iCloud Drive
`Shortcuts/Highdeas/` → iCloud for Windows mirrors it to the PC (the hours-late link this
project removes) → `service.refresh()` ingests and transcribes it into a local Flask
inbox → Submit routes it to Notesnook or Google Drive and retires it to a bin.

Facts the upload work must honor (`src/highdeas/ingest.py`):

- Ingest adopts any file in `HIGHDEAS_INBOX_DIR` whose suffix is in `AUDIO_EXTENSIONS`
  (`.m4a .mp3 .wav .aac .caf .aiff`). It can see a file the moment it exists, so an
  upload must never leave a partial file under an audio extension — stream to a temp
  name ingest ignores (e.g. `.part`), then rename into place.
- Recordings are keyed by content (`recording_key`): a fingerprint of size + embedded
  recording time, folded into the filename. Re-uploading the same file is therefore
  already harmless, and recycled filenames can't collide. Don't invent a parallel
  dedupe scheme.
- `recording_time` prefers the `moov/mvhd` creation time inside the m4a; iOS stamps it
  when recording. (The append-era caveat about `AVMutableComposition` exports writing a
  fresh container is moot now that append is cut — plain `AVAudioRecorder` output
  carries the real recording time.)
- While the inbox page is open it polls `GET /pending`, which calls `service.refresh()`,
  so a file dropped into the inbox dir is adopted within a poll. The upload endpoint may
  also trigger a refresh itself so adoption doesn't wait for a page to be open.

Server binding today (`src/highdeas/app.py`): desktop mode runs Flask on a **random,
loopback-only port** behind the native window; browser mode on `127.0.0.1:HIGHDEAS_PORT`
(default 5000). Nothing is reachable from the LAN yet.

## The wire contract (as built, 2026-07-10)

`POST /upload` — multipart form, one file field named **`audio`**, header
**`Authorization: Bearer <HIGHDEAS_UPLOAD_TOKEN>`**. Responses: **201**
`{"stored": "<keyed filename>"}` on first receipt; **200** same body when the
server already has it (retry of a landed upload); **400** no/empty file; **401**
missing/bad token; **413** body over 1GB; **415** suffix not in
`AUDIO_EXTENSIONS`. Any 2xx means durably stored — the phone may delete. 4xx
means retrying won't help (fix settings / drop the file); everything else
retries with backoff.

Known limitation, accepted for v1: retry dedupe rides `recording_key`, whose
fingerprint falls back to file mtime for formats without an embedded
`moov/mvhd` time (.wav/.mp3/.aac/.caf/.aiff). A retried non-m4a upload whose
2xx was lost re-lands under a fresh key as a duplicate memo. Our client only
sends m4a (AVAudioRecorder stamps the container), so this bites only foreign
clients; fixing it would mean changing the fingerprint scheme itself.

## Workstream 1 — server (Python, this repo, strict TDD)

1. **`POST /upload`** on the Flask app: multipart audio file, auth via a shared token
   (`HIGHDEAS_UPLOAD_TOKEN`, new `.env` key — add it to `.env.example` and the README
   config table). Write atomically into `HIGHDEAS_INBOX_DIR` as above. Respond 2xx only
   once the file is fully in place — the phone clears a recording on 2xx and must never
   lose one. Reject a missing/bad token (401) and non-audio suffixes.
2. **A stable, LAN-reachable listener.** The phone needs a fixed `http://<pc>:<port>`
   in both desktop and browser modes. Prefer exposing **only** the upload endpoint on
   `0.0.0.0` (a second listener/port) rather than binding the whole inbox UI to the
   LAN — the UI's submit/delete routes shouldn't become LAN-wide side effects. New env
   var for the port.
3. **Windows-side notes for the README** (Douglas applies them on the PC after
   pulling): a one-time Windows Firewall inbound allowance for that port, setting
   `HIGHDEAS_UPLOAD_TOKEN` in `.env`, and finding the PC's LAN address to enter in the
   phone's settings screen. Reachability beyond the home LAN (e.g. Tailscale) was
   discussed but is not part of v1 — the retry queue covers away-from-home recording.

## Workstream 2 — the app (`ios/`)

- SwiftUI. His iPhone runs iOS 26.x (answered at kickoff, 2026-07-10) — set the
  deployment target comfortably below (iOS 17+) so a replacement phone could run it.
- Record: `AVAudioSession` (`.playAndRecord`), `AVAudioRecorder` → AAC `.m4a` in the
  app's Documents; `UIBackgroundModes: audio` so recording survives the screen locking.
- List: local recordings with their state — recording / local / queued / sent. Play
  with a scrub slider (`AVAudioPlayer` + `Slider`).
- Push: multipart POST with the token header; a `URLSession` background session with
  retry/backoff; mark sent and clear only on 2xx. Auto-push fires when recording stops.
  **The backoff belongs to the session daemon, not to a timer in the app** — see below.
- Settings: server URLs (one machine per line — the fan-out era) + token.
- Tests: XCTest the pure logic (queue state machine, request building). The
  audio/hardware layer is verified on the device — don't fake-TDD it.

### Who owns the wait between attempts (learned the hard way, 2026-08-08)

The kickoff recorded a simulator observation from 2026-07-10: with the server
down, the system session appeared to hold the failed task and retry it on its
own, delivering with no user action once the server came back. **On the phone it
does not go that way.** A transfer toward a machine that is asleep or off the
network comes back as a completed task with an error, the app is woken to hear
it, and from there the retry was the app's problem — a `notBefore` backoff that
only a five-second `Timer` inside the app ever consulted. iOS suspends the app
seconds later and that timer stops, so the next attempt waited for Douglas to
open the app. Three notes sat on the phone from Aug 7 to Aug 8 and left within
ten seconds of it being launched; they had sat through hours in which the Mac
was awake with its listener up.

So the wait is handed to the session daemon instead. Every queued entry is
pushed straight away and its backoff travels with it as
`URLSessionTask.earliestBeginDate`; the daemon starts the transfer at that
moment whether or not the app is running, and relaunches it to deliver the
outcome, which schedules the next attempt. The chain sustains itself with the
app dead. `UploadQueue.next()` therefore hands over anything not already in
flight — a backoff is no longer a reason to hold an entry back — and
`flightBeginsAt` is *when it may start*, not when it did, so nothing measures
silence against a transfer that has not begun.

Verified on the device (2026-08-08, iPhone 16 Pro, iOS 26.5.2): pointed at a
listener that was down, then killed the app outright (`devicectl process signal
SIGKILL`), then brought the listener up. Both queued recordings arrived while
`devicectl info processes` showed the app not running.

### The staging folder, and why a confirmation leaves its siblings flying (2026-08-08)

Each push assembles its multipart body into a file under
`Library/Caches/upload-bodies/` for the background session to stream from, and
deletes it when that task calls back. Nine had collected on the phone by
2026-08-08, the oldest ten days old, because some tasks never call back: a
fan-out pushes to every machine at once, the first 2xx releases the recording
(`mac-peer.md`, "Settled 2026-08-03") and takes the queue entry with it, and the
transfers toward the machines that hadn't answered are then held by iOS
indefinitely and silently, watched by nobody.

**Those siblings are left flying on purpose.** Cancelling them on the first
confirmation would tidy the folder at the cost of the delivery Douglas's rule
takes for granted: with both machines up, the sibling transfer puts the note on
the other desk in seconds, which beats waiting for the store to sync it. It still
lands after the recording is deleted from the phone, because the body is a
complete copy of it, written before the task started. Cancelling is a change to
delivery behaviour, and that call is Douglas's — ask before making it.

So the folder is swept instead, once at launch, for bodies older than a day —
the shape `_sweep_stale_staging` uses on the server's own `.part` leftovers, at
the phone's timescale. A *fresh* body is never touched: it belongs to a transfer
under way, or to the instant in `push` between the body being written and the
task existing to stream it. A day is far past the queue's own two-minute patience
with a silent flight, so nothing that old is still expected to land.
`Library/Caches` is purgeable by iOS, so this was untidiness rather than a risk
to a recording — hence one sweep at launch and no running upkeep.

## Dev loop on the Mac

- Python baseline first: `/opt/homebrew/bin/python3.14 -m venv .venv` (the Mac's bare
  `python3` is the ancient system 3.9, whose pip can't even do a pyproject editable
  install), `.venv/bin/python -m pip install -e ".[dev]"`, then
  `.venv/bin/python -m pytest` — green before touching anything. The code is cross-platform; the Windows-only bits
  (WebView2 window, taskbar identity) are guarded and fall back cleanly.
- Run the server in browser mode with temp dirs (the defaults are Windows paths):
  `HIGHDEAS_DESKTOP=0` plus `HIGHDEAS_INBOX_DIR`, `HIGHDEAS_BIN_DIR`, and `HIGHDEAS_DB` pointed at
  scratch locations, then `.venv/bin/python -m highdeas.app`. Phone and Mac on the same
  Wi-Fi gives a true end-to-end loop; production is the same code on the PC once
  Douglas pulls.
- Heads-up: opening a memo's editor autoplays its audio by default — recordings are
  private, so mute the Mac before driving the UI, or untick the Auto-play box in the
  player bar (the choice sticks across every future note).
- The first transcription downloads the ASR model and takes ~15s; it runs in the
  background and doesn't matter to upload testing.

## Working agreements (unchanged from every Highdeas session)

- Never work in the primary checkout — `git worktree add .claude/worktrees/<name> -b
  claude/<name>`.
- Python side: strict red-green-refactor TDD; the whole suite green (zero failures,
  errors, skips) before every commit; small single-purpose commits.
- Keep `.env.example`, the README config table, and `pyproject.toml` in sync with what
  the code reads.

## Suggested order

1. Mac baseline: venv, pytest green, server runs in browser mode.
2. Settle the auto-push question with Douglas.
3. Server: `/upload` + the reachable listener (TDD).
4. Xcode skeleton in `ios/` running on his iPhone under free signing — prove the 7-day
   re-sign loop early; it's the only genuinely unfamiliar mechanic.
5. Record → push, end to end against the Mac-hosted server.
6. Scrub playback.
7. README: the Windows-side setup notes and a short section on the iOS app.
