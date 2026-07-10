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
    @AppStorage("serverURL") var serverURL: String = "" { didSet { wake() } }
    @AppStorage("uploadToken") var uploadToken: String = "" { didSet { wake() } }

    let recorder = Recorder()
    private let uploader = Uploader()
    private var queue = UploadQueue()
    private var pump: Timer?

    /// Recordings still in flight toward the server live here; recording
    /// happens in a sibling folder so a half-written file can never be
    /// mistaken for a finished memo and pushed early.
    let recordingsDirectory: URL
    private let activeDirectory: URL

    var endpoint: UploadEndpoint? {
        UploadEndpoint(serverURL: serverURL, token: uploadToken)
    }

    init(under root: URL = .documentsDirectory) {
        recordingsDirectory = root.appending(path: "Recordings", directoryHint: .isDirectory)
        activeDirectory = root.appending(path: "Recording-in-progress", directoryHint: .isDirectory)
        recorder.onFinished = { [weak self] url in self?.adopt(url) }
        uploader.onOutcome = { [weak self] fileName, outcome in
            self?.handle(fileName, outcome)
        }
        adoptLeftovers()
        wake()
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
        guard let endpoint else { return }
        while let ready = queue.next(at: now) {
            queue.markInFlight(ready.fileName)
            uploader.push(recordingsDirectory.appending(path: ready.fileName), to: endpoint)
        }
    }

    private func handle(_ fileName: String, _ outcome: UploadOutcome) {
        switch outcome {
        case .confirmed:
            // Remove the entry first, then the file: a crash in between costs
            // one duplicate upload (the server dedupes), never a lost memo.
            queue.confirmSent(fileName)
            try? FileManager.default.removeItem(
                at: recordingsDirectory.appending(path: fileName))
        case .blocked(let reason):
            queue.block(fileName, reason: reason, at: Date())
        case .retriable:
            queue.retryLater(fileName, at: Date())
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
        if entry.inFlight { return .uploading }
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
