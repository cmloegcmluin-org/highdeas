import Foundation
import Testing
@testable import HighdeasKit

@Suite struct UploadEndpointTests {
    @Test func parsesAndTrimsTheSettingsFields() {
        let endpoint = UploadEndpoint(serverURL: " http://192.168.1.23:5055 ", token: " sekrit \n")
        #expect(endpoint?.baseURL.absoluteString == "http://192.168.1.23:5055")
        #expect(endpoint?.token == "sekrit")
        #expect(endpoint?.uploadURL.absoluteString == "http://192.168.1.23:5055/upload")
    }

    @Test func rejectsWhatCannotReachAServer() {
        #expect(UploadEndpoint(serverURL: "", token: "t") == nil)
        #expect(UploadEndpoint(serverURL: "http://192.168.1.23:5055", token: "  ") == nil)
        #expect(UploadEndpoint(serverURL: "192.168.1.23:5055", token: "t") == nil)  // no scheme
        #expect(UploadEndpoint(serverURL: "ftp://192.168.1.23", token: "t") == nil)
        #expect(UploadEndpoint(serverURL: "http://", token: "t") == nil)  // no host
    }
}

@Suite struct UploadOutcomeTests {
    @Test func mapsStatusCodesToWhatTheQueueShouldDo() {
        #expect(UploadOutcome(statusCode: 201) == .confirmed)
        #expect(UploadOutcome(statusCode: 200) == .confirmed)  // retry of a landed upload
        #expect(UploadOutcome(statusCode: nil) == .retriable)  // transport error
        #expect(UploadOutcome(statusCode: 503) == .retriable)
        if case .blocked = UploadOutcome(statusCode: 401) {} else {
            Issue.record("401 must block, not spin on retries")
        }
        if case .blocked = UploadOutcome(statusCode: 415) {} else {
            Issue.record("415 must block, not spin on retries")
        }
    }
}

@Suite struct MultipartUploadTests {
    private let endpoint = UploadEndpoint(serverURL: "http://10.0.0.5:5055", token: "sekrit")!

    @Test func requestCarriesTokenAndBoundary() {
        let request = MultipartUpload.request(to: endpoint, boundary: "B0UNDARY")
        #expect(request.httpMethod == "POST")
        #expect(request.url?.absoluteString == "http://10.0.0.5:5055/upload")
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer sekrit")
        #expect(request.value(forHTTPHeaderField: "Content-Type")
                == "multipart/form-data; boundary=B0UNDARY")
    }

    @Test func bodyIsTheExactWireFormatTheServerParses() throws {
        // Byte-for-byte: Flask/werkzeug reads an `audio` form file with CRLF
        // separators. Pin the frame so a refactor can't silently bend it.
        let recording = FileManager.default.temporaryDirectory
            .appending(path: "memo-test-\(UUID().uuidString).m4a")
        try Data("AUDIOBYTES".utf8).write(to: recording)
        defer { try? FileManager.default.removeItem(at: recording) }
        let body = FileManager.default.temporaryDirectory
            .appending(path: "body-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: body) }

        try MultipartUpload.writeBody(of: recording, boundary: "B", to: body)

        let expected = "--B\r\n"
            + "Content-Disposition: form-data; name=\"audio\"; filename=\"\(recording.lastPathComponent)\"\r\n"
            + "Content-Type: audio/mp4\r\n\r\n"
            + "AUDIOBYTES"
            + "\r\n--B--\r\n"
        #expect(try Data(contentsOf: body) == Data(expected.utf8))
    }

    @Test func filenamesCannotBreakOutOfTheQuotedHeader() {
        let prefix = MultipartUpload.bodyPrefix(fileName: "a\"b\r\nc.m4a", boundary: "B")
        let text = String(decoding: prefix, as: UTF8.self)
        #expect(text.contains("filename=\"a_b__c.m4a\""))
    }
}
