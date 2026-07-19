import Foundation
import SwiftUI
import HighdeasKit

/// One recording as the list shows it. The list is the retry queue with a short
/// tail: a row exists as long as the file does, the file is deleted only when the
/// server confirms receipt, and the row then stays a few seconds more to say so
/// (see DeliveryReceipts) instead of blinking out.
struct RecordingItem: Identifiable, Equatable {
    enum State: Equatable {
        case recording
        case uploading
        case awaitingMachine
        case queued
        case blocked(String)
        case delivered
    }

    let fileName: String
    let url: URL
    let recordedAt: Date
    var state: State

    var id: String { fileName }

    /// Whether there is still a recording here to play. One being written and one
    /// already handed over both have a row and no file behind it.
    var canPlay: Bool { state != .recording && state != .delivered }
}

/// The glue: recorder in, disk as truth, queue rules from HighdeasKit,
/// uploader out. All on the main actor — the pure logic it defers to is
/// synchronous and instant.
@MainActor
final class CaptureModel: ObservableObject {
    @Published private(set) var items: [RecordingItem] = []
    /// Why recording could not start, for the UI to say out loud. A record
    /// button that silently does nothing (denied microphone, audio-session
    /// failure) reads as a lost memo.
    @Published var recordingProblem: String?
    // A settings change means the old failures say nothing about the new
    // world: retry everything now rather than waiting out backoff timers
    // aimed at addresses (or a token) that no longer exist.
    @AppStorage("serverURLs") var serverURLs: String = "" { didSet { queue.expedite(); wake() } }
    @AppStorage("uploadToken") var uploadToken: String = "" { didSet { queue.expedite(); wake() } }

    let recorder = Recorder()
    let uploader = Uploader()
    private var queue = UploadQueue()
    /// Rows for recordings already delivered, kept a few seconds so a note never
    /// disappears from the phone before the desk has it on screen.
    private var receipts = DeliveryReceipts()
    private var pump: Timer?
    private var receiptSweep: Timer?

    /// Recordings still in flight toward the server live here; recording
    /// happens in a sibling folder so a half-written file can never be
    /// mistaken for a finished memo and pushed early.
    let recordingsDirectory: URL
    private let activeDirectory: URL

    /// Every machine the phone delivers to — one per Settings line. They all
    /// share one store (Syncthing) and one token, so pushing to all of them
    /// at once is safe: the first 2xx wins, the rest answer "already have it".
    var endpoints: [UploadEndpoint] {
        UploadEndpoint.list(from: serverURLs, token: uploadToken)
    }

    init(under root: URL = .documentsDirectory) {
        recordingsDirectory = root.appending(path: "Recordings", directoryHint: .isDirectory)
        activeDirectory = root.appending(path: "Recording-in-progress", directoryHint: .isDirectory)
        // One-time migration: the single-server era stored one URL under
        // "serverURL"; carry it into the list so an updated app keeps pushing.
        if serverURLs.isEmpty,
           let old = UserDefaults.standard.string(forKey: "serverURL"), !old.isEmpty {
            serverURLs = old
        }
        recorder.onFinished = { [weak self] url in self?.adopt(url) }
        uploader.onOutcome = { [weak self] fileName, outcome in
            self?.handle(fileName, outcome)
        }
        adoptLeftovers()
        uploader.reconnect()  // collect outcomes that arrived while the app was gone
        wake()
        nudgeLocalNetwork()
        // A slow heartbeat retries what backoff has released and refreshes
        // the countdowns; the real triggers are stop, foreground, and outcome.
        pump = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.wake() }
        }
    }

    func toggleRecording() {
        if recorder.isRecording {
            recorder.stop()  // adopt() runs via onFinished
        } else {
            do {
                try recorder.start(into: activeDirectory)
            } catch {
                recordingProblem = String(describing: error)
                NSLog("Highdeas: recording could not start: %@", String(describing: error))
            }
            rebuildItems()
        }
    }

    /// iOS grants LAN access per-app, and a *background* session's traffic
    /// can be silently denied without the permission prompt ever appearing.
    /// One tiny foreground request makes the system ask properly.
    func nudgeLocalNetwork() {
        guard let first = endpoints.first else { return }
        var request = URLRequest(url: first.baseURL)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request).resume()
    }

    /// Sync with the disk and push whatever is ready. Safe to call often.
    func wake() {
        receipts.prune(at: Date())
        syncWithDisk()
        pumpQueue()
        rebuildItems()
        scheduleReceiptSweep()
    }

    /// Wake again exactly when the oldest receipt stops being true. Left to the
    /// 5-second heartbeat a delivered row would linger for whatever part of a
    /// tick it happened to land in, so two notes sent seconds apart would clear
    /// after visibly different waits.
    private func scheduleReceiptSweep() {
        receiptSweep?.invalidate()
        receiptSweep = nil
        guard let due = receipts.nextExpiry() else { return }
        receiptSweep = Timer.scheduledTimer(
            withTimeInterval: max(0.05, due.timeIntervalSinceNow), repeats: false) { [weak self] _ in
            Task { @MainActor in self?.wake() }
        }
    }

    /// A finished recording moves from the in-progress folder into the queue's
    /// folder; only then does it exist as far as pushing is concerned.
    private func adopt(_ url: URL) {
        try? FileManager.default.createDirectory(
            at: recordingsDirectory, withIntermediateDirectories: true)
        let landed = recordingsDirectory.appending(path: url.lastPathComponent)
        try? FileManager.default.moveItem(at: url, to: landed)
        wake()
    }

    /// A crash or force-quit mid-recording leaves a file in the in-progress
    /// folder. What was captured up to that moment is still a memo — adopt it
    /// on the next launch rather than leaving it invisible. But a header-only
    /// torso (killed before any audio frames were written) is not a memo:
    /// pushing one plants a file in the PC inbox that fails transcription on
    /// every refresh, forever. Nothing audible fits in a kilobyte.
    private func adoptLeftovers() {
        for url in files(in: activeDirectory) {
            let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            if size < 1024 {
                try? FileManager.default.removeItem(at: url)
                continue
            }
            try? FileManager.default.createDirectory(
                at: recordingsDirectory, withIntermediateDirectories: true)
            try? FileManager.default.moveItem(
                at: url, to: recordingsDirectory.appending(path: url.lastPathComponent))
        }
    }

    private func syncWithDisk() {
        queue.sync(withFiles: files(in: recordingsDirectory).map(\.lastPathComponent).sorted())
    }

    private func pumpQueue(now: Date = Date()) {
        // A flight iOS has quietly parked (background tasks toward machines
        // it can't reach never call back) must not wedge a note until the
        // next cold launch: past the deadline it rejoins the queue and its
        // zombie tasks are cancelled. Then the ordinary push resumes.
        for stale in queue.releaseStaleFlights(at: now) {
            uploader.abandon(stale)
        }
        let peers = endpoints
        guard !peers.isEmpty else { return }
        while let ready = queue.next(at: now) {
            queue.markInFlight(ready.fileName, expecting: peers.count)
            for peer in peers {
                uploader.push(recordingsDirectory.appending(path: ready.fileName), to: peer)
            }
        }
    }

    private func handle(_ fileName: String, _ outcome: UploadOutcome) {
        // The queue arbitrates the fan-out: first confirmation wins, failure
        // waits for the last machine to answer.
        queue.resolve(fileName, outcome, at: Date())
        if case .confirmed = outcome, let recordedAt = recordedDate(of: fileName) {
            // The row stays on for a few seconds to say it arrived, so the note is
            // never nowhere. Read the recording's own time first: in a moment there
            // will be no file left to read it from — and if there is no file to read
            // it from now, this is a late echo of a delivery already seen and gone
            // (a background outcome replayed on relaunch), not a note just landed.
            // Announcing that one would put "Delivered" at the foot of the list,
            // dated distantPast, about a recording the phone finished with long ago.
            receipts.confirm(fileName, recordedAt: recordedAt, at: Date())
            // Entry first, file second: a crash in between costs one duplicate
            // upload (the server dedupes), never a lost memo.
            try? FileManager.default.removeItem(
                at: recordingsDirectory.appending(path: fileName))
        }
        wake()
    }

    private func rebuildItems() {
        var rows = queue.pending.map { entry in
            RecordingItem(
                fileName: entry.fileName,
                url: recordingsDirectory.appending(path: entry.fileName),
                recordedAt: creationDate(of: entry.fileName),
                state: state(of: entry))
        }
        // Delivered rows sit among the rest by the time each was spoken, so a note
        // that has just landed stays exactly where it was and only its line changes.
        // Its recorded time is the receipt's: the file it came from is gone.
        //
        // Unless it isn't: if the delete after a confirmation failed, the disk scan
        // takes the file back into the queue, and the row it owns there is the true
        // one — the recording really is still here and really will be pushed again.
        // A receipt shown alongside it would be a second row under the same id,
        // which is a promise to SwiftUI that this code does not get to break.
        let stillPending = Set(queue.pending.map(\.fileName))
        rows += receipts.showing.filter { !stillPending.contains($0.fileName) }.map { receipt in
            RecordingItem(
                fileName: receipt.fileName,
                url: recordingsDirectory.appending(path: receipt.fileName),
                recordedAt: receipt.recordedAt,
                state: .delivered)
        }
        if recorder.isRecording {
            rows.append(RecordingItem(
                fileName: "recording-now", url: activeDirectory,
                recordedAt: Date(), state: .recording))
        }
        items = rows.sorted { $0.recordedAt > $1.recordedAt }
    }

    private func state(of entry: PendingUpload) -> RecordingItem.State {
        // No machine around — a silent flight, or a round nobody confirmed —
        // is an ordinary afternoon out, not an incident: one calm state
        // instead of an alarm and a retry countdown. Refusals stay loud.
        if entry.awaitingMachine(at: Date()) { return .awaitingMachine }
        if entry.inFlight { return .uploading }
        if let reason = entry.blockedReason { return .blocked(reason) }
        return .queued
    }

    private func files(in directory: URL) -> [URL] {
        ((try? FileManager.default.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: [.creationDateKey])) ?? [])
            .filter { $0.pathExtension.lowercased() == "m4a" }
    }

    private func creationDate(of fileName: String) -> Date {
        recordedDate(of: fileName) ?? .distantPast
    }

    /// When the recording was spoken, or nil if there is no longer a file to ask.
    /// A row built from the queue can fall back to distantPast and merely sort
    /// oddly; a receipt cannot, because a receipt is a claim that this recording
    /// just left the phone.
    private func recordedDate(of fileName: String) -> Date? {
        let url = recordingsDirectory.appending(path: fileName)
        return (try? url.resourceValues(forKeys: [.creationDateKey]))?.creationDate
    }
}
