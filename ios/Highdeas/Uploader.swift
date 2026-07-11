import Foundation
import HighdeasKit

/// Drives the actual transfers on a background `URLSession`, so an upload
/// started before the screen locked (or the user switched apps) keeps going.
/// Each finished attempt is reported back as an `UploadOutcome`; the queue
/// rules live in HighdeasKit, not here.
final class Uploader: NSObject, URLSessionDataDelegate {
    var onOutcome: (@MainActor (String, UploadOutcome) -> Void)?

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(
            withIdentifier: "com.cmloegcmluin.highdeas.uploads")
        config.isDiscretionary = false
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    /// Assembled multipart bodies wait here while URLSession streams them;
    /// Caches is right because losing one only costs a retry.
    private var bodiesDirectory: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appending(path: "upload-bodies", directoryHint: .isDirectory)
    }

    func push(_ recording: URL, to endpoint: UploadEndpoint) {
        let boundary = "highdeas-\(UUID().uuidString)"
        do {
            try FileManager.default.createDirectory(
                at: bodiesDirectory, withIntermediateDirectories: true)
            // One body file per task: a fan-out pushes the same recording to
            // several machines at once, and they must not share staging.
            let bodyName = recording.lastPathComponent + "." + UUID().uuidString + ".body"
            let body = bodiesDirectory.appending(path: bodyName)
            try MultipartUpload.writeBody(of: recording, boundary: boundary, to: body)
            let task = session.uploadTask(
                with: MultipartUpload.request(to: endpoint, boundary: boundary), fromFile: body)
            task.taskDescription = recording.lastPathComponent + "|" + bodyName
            task.resume()
        } catch {
            report(recording.lastPathComponent, .retriable)
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                didCompleteWithError error: Error?) {
        guard let description = task.taskDescription else { return }
        let parts = description.split(separator: "|", maxSplits: 1).map(String.init)
        let fileName = parts[0]
        let status = (task.response as? HTTPURLResponse)?.statusCode
        let outcome = error == nil ? UploadOutcome(statusCode: status) : UploadOutcome.retriable
        if parts.count == 2 {
            try? FileManager.default.removeItem(at: bodiesDirectory.appending(path: parts[1]))
        }
        report(fileName, outcome)
    }

    private nonisolated func report(_ fileName: String, _ outcome: UploadOutcome) {
        Task { @MainActor in self.onOutcome?(fileName, outcome) }
    }
}
