import Foundation

/// Where and how to reach the Highdeas server — the two Settings fields,
/// validated. `nil` means the app isn't configured yet and the queue waits.
public struct UploadEndpoint: Equatable, Sendable {
    public let baseURL: URL
    public let token: String

    public init?(serverURL: String, token: String) {
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedToken.isEmpty,
              let url = URL(string: trimmedURL),
              let scheme = url.scheme, ["http", "https"].contains(scheme),
              url.host() != nil
        else { return nil }
        self.baseURL = url
        self.token = trimmedToken
    }

    /// POST target: the server exposes exactly one route to the LAN.
    public var uploadURL: URL {
        baseURL.appending(path: "upload")
    }
}

/// What one finished upload attempt means for the queue.
public enum UploadOutcome: Equatable, Sendable {
    /// 2xx — the server has the recording durably; the phone may delete it.
    case confirmed
    /// The server answered but refused (401 bad token, 415 wrong suffix…):
    /// retrying on a timer won't help, a settings/config fix will.
    case blocked(String)
    /// Transport error or 5xx — try again after backoff.
    case retriable

    public init(statusCode: Int?) {
        switch statusCode {
        case .some(200...299): self = .confirmed
        case .some(401): self = .blocked("The server rejected the upload token — check Settings.")
        case .some(400...499): self = .blocked("The server refused this recording (HTTP \(statusCode!)).")
        default: self = .retriable
        }
    }
}

/// Builds the multipart POST the server's /upload route expects: one `audio`
/// field carrying the recording, a Bearer token header. Pure functions —
/// bytes in, bytes out — so the exact wire format is pinned by tests.
public enum MultipartUpload {
    /// The request without its body (the body is uploaded from a file so a
    /// background URLSession can take over the transfer).
    public static func request(to endpoint: UploadEndpoint, boundary: String) -> URLRequest {
        var request = URLRequest(url: endpoint.uploadURL)
        request.httpMethod = "POST"
        request.setValue("Bearer \(endpoint.token)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)",
                         forHTTPHeaderField: "Content-Type")
        return request
    }

    public static func bodyPrefix(fileName: String, boundary: String) -> Data {
        Data("""
        --\(boundary)\r
        Content-Disposition: form-data; name="audio"; filename="\(sanitized(fileName))"\r
        Content-Type: audio/mp4\r
        \r

        """.utf8)
    }

    public static func bodySuffix(boundary: String) -> Data {
        Data("\r\n--\(boundary)--\r\n".utf8)
    }

    /// Assemble the whole multipart body on disk, next to nothing in memory —
    /// `URLSession.uploadTask(with:fromFile:)` streams it from there, which is
    /// what lets an upload keep going after the app is backgrounded.
    public static func writeBody(of recording: URL, boundary: String, to destination: URL) throws {
        var body = bodyPrefix(fileName: recording.lastPathComponent, boundary: boundary)
        body.append(try Data(contentsOf: recording, options: .mappedIfSafe))
        body.append(bodySuffix(boundary: boundary))
        try body.write(to: destination)
    }

    /// A filename travels inside a quoted multipart header, so strip the two
    /// characters that could break out of it. The server re-sanitizes anyway.
    private static func sanitized(_ fileName: String) -> String {
        fileName.replacingOccurrences(of: "\"", with: "_")
            .replacingOccurrences(of: "\r", with: "_")
            .replacingOccurrences(of: "\n", with: "_")
    }
}
