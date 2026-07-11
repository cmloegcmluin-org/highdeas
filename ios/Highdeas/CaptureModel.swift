import Foundation
import SwiftUI
import HighdeasKit

/// One recording as the list shows it. The list *is* the retry queue: a row
/// exists exactly as long as the file does, and the file is deleted only when
/// the server confirms receipt.
struct RecordingItem: Identifiable, Equatable {
    enum State: Equatable {
        case recording
        case uploading
        case stillTrying
        case queued
        case waiting(until: Date)
        case blocked(String)
    }

    let fileName: String
    let url: URL
    let recordedAt: Date
    var state: State

    var id: String { fileName }
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
    @AppStorage("serverURLs") var serverURLs: String = "" { didSet { wake() } }
    @AppStorage("uploadToken") var uploadToken: String = "" { didSet { wake() } }

    let recorder = Recorder()
    let uploader = Uploader()
    private var queue = UploadQueue()
    private var pump: Timer?

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
        syncWithDisk()
        pumpQueue()
        rebuildItems()
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
        if case .confirmed = outcome {
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
        if recorder.isRecording {
            rows.append(RecordingItem(
                fileName: "recording-now", url: activeDirectory,
                recordedAt: Date(), state: .recording))
        }
        items = rows.sorted { $0.recordedAt > $1.recordedAt }
    }

    private func state(of entry: PendingUpload) -> RecordingItem.State {
        if entry.inFlight {
            // A flight nothing has answered in minutes is stuck somewhere —
            // machines asleep, or the phone lacks Local Network permission.
            // "Uploading…" would be a lie; say what's actually happening.
            if let started = entry.flightStartedAt, Date().timeIntervalSince(started) > 120 {
                return .stillTrying
            }
            return .uploading
        }
        if let reason = entry.blockedReason { return .blocked(reason) }
        if entry.notBefore > Date() { return .waiting(until: entry.notBefore) }
        return .queued
    }

    private func files(in directory: URL) -> [URL] {
        ((try? FileManager.default.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: [.creationDateKey])) ?? [])
            .filter { $0.pathExtension.lowercased() == "m4a" }
    }

    private func creationDate(of fileName: String) -> Date {
        let url = recordingsDirectory.appending(path: fileName)
        let values = try? url.resourceValues(forKeys: [.creationDateKey])
        return values?.creationDate ?? .distantPast
    }
}
