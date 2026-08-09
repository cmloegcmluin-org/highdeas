import Foundation
import HighdeasKit

/// Drives the actual transfers on a background `URLSession`, so an upload
/// started before the screen locked (or the user switched apps) keeps going.
/// Each finished attempt is reported back as an `UploadOutcome`; the queue
/// rules live in HighdeasKit, not here.
final class Uploader: NSObject, URLSessionDataDelegate {
    /// Recording, the machine that answered, what it said. The queue records
    /// deliveries per machine, so an outcome that didn't say who it came from
    /// would be unusable.
    var onOutcome: (@MainActor (String, String, UploadOutcome) -> Void)?
    /// The system's "wake finished" handler, parked here between
    /// handleEventsForBackgroundURLSession and the session draining its
    /// queued delegate events.
    var backgroundCompletionHandler: (() -> Void)?

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(
            withIdentifier: "com.cmloegcmluin.highdeas.uploads")
        config.isDiscretionary = false
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    /// Reattach to the background session by its identifier. Outcomes that
    /// arrived while the app was gone are delivered only to a session object
    /// that exists — a lazily-created one that waits for the next push would
    /// leave a confirmed upload stuck reading "Uploading…" forever.
    func reconnect() {
        _ = session
    }

    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async {
            self.backgroundCompletionHandler?()
            self.backgroundCompletionHandler = nil
        }
    }

    /// Assembled multipart bodies wait here while URLSession streams them;
    /// Caches is right because losing one only costs a retry.
    private var bodiesDirectory: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appending(path: "upload-bodies", directoryHint: .isDirectory)
    }

    /// Clear out the bodies of transfers that are never going to call back —
    /// the ones iOS is still holding for a machine it can't reach, whose queue
    /// entry left the moment another machine confirmed the recording, so
    /// nothing is watching them any more. Left to itself the folder gains one
    /// per fan-out toward a machine that is away.
    ///
    /// Once at launch is enough: this is untidiness in a purgeable cache, not a
    /// risk to a recording. Which leftovers are stale, and why a fresh one is
    /// untouchable, is `StagedBodies`' business.
    func sweepStaleBodies() {
        let leftovers = (try? FileManager.default.contentsOfDirectory(
            at: bodiesDirectory,
            includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        for name in StagedBodies.stale(among: leftovers.map(described), at: Date()) {
            try? FileManager.default.removeItem(at: bodiesDirectory.appending(path: name))
        }
    }

    private func described(_ leftover: URL) -> StagedBody {
        StagedBody(
            name: leftover.lastPathComponent,
            modified: (try? leftover.resourceValues(forKeys: [.contentModificationDateKey]))?
                .contentModificationDate)
    }

    /// Hand one transfer to the session. `notBefore` in the future schedules it
    /// rather than starting it: the session daemon owns the wait, and starts the
    /// transfer at that moment whether or not this app is still running. That is
    /// the whole of the backoff — a timer inside the app only ticks while the
    /// app is awake, so a note that failed once would sit until the user next
    /// opened it.
    func push(_ recording: URL, to endpoint: UploadEndpoint, notBefore: Date) {
        let boundary = "highdeas-\(UUID().uuidString)"
        do {
            try FileManager.default.createDirectory(
                at: bodiesDirectory, withIntermediateDirectories: true)
            // One body file per task: a fan-out pushes the same recording to
            // several machines at once, and they must not share staging.
            let bodyName = recording.lastPathComponent + "." + UUID().uuidString
                + StagedBodies.suffix
            let body = bodiesDirectory.appending(path: bodyName)
            try MultipartUpload.writeBody(of: recording, boundary: boundary, to: body)
            let task = session.uploadTask(
                with: MultipartUpload.request(to: endpoint, boundary: boundary), fromFile: body)
            // recording | machine | staged body. None of the three can contain a
            // pipe: the first two are generated names, the third an address.
            task.taskDescription = [recording.lastPathComponent, endpoint.key, bodyName]
                .joined(separator: "|")
            if notBefore > Date() { task.earliestBeginDate = notBefore }
            task.resume()
        } catch {
            report(recording.lastPathComponent, endpoint.key, .retriable)
        }
    }

    /// Cancel the tasks of a flight the queue has given up on, so an
    /// afternoon of re-pushes can't pile up transfers the system is holding
    /// for machines it can't reach. Each cancellation echoes back through
    /// didCompleteWithError (cleaning up its body file on the way); the
    /// queue ignores a dead flight's echoes.
    func abandon(_ fileName: String) {
        session.getAllTasks { tasks in
            for task in tasks
            where task.taskDescription?.hasPrefix(fileName + "|") == true {
                task.cancel()
            }
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                didCompleteWithError error: Error?) {
        guard let description = task.taskDescription else { return }
        let parts = description.split(separator: "|", maxSplits: 2).map(String.init)
        guard parts.count >= 2 else { return }
        // The staged body is always last, and wants clearing either way — a task
        // an older build started names no machine (recording|body), so its answer
        // can't be recorded against one. The stale-flight release re-pushes it.
        try? FileManager.default.removeItem(
            at: bodiesDirectory.appending(path: parts[parts.count - 1]))
        guard parts.count == 3 else { return }
        let status = (task.response as? HTTPURLResponse)?.statusCode
        let outcome = error == nil ? UploadOutcome(statusCode: status) : UploadOutcome.retriable
        report(parts[0], parts[1], outcome)
    }

    private nonisolated func report(_ fileName: String, _ peer: String,
                                    _ outcome: UploadOutcome) {
        Task { @MainActor in self.onOutcome?(fileName, peer, outcome) }
    }
}
