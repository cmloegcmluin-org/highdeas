import AVFoundation
import UIKit

/// Owns the microphone: one `AVAudioRecorder` writing AAC `.m4a`, the same
/// container the old Shortcut produced, so the server's ingest facts hold.
/// `UIBackgroundModes: audio` in Info.plist keeps a running recording alive
/// after the screen locks. Hardware behavior is verified on the device — the
/// pure logic lives in HighdeasKit, not here.
@MainActor
final class Recorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published private(set) var isRecording = false
    @Published private(set) var elapsed: TimeInterval = 0

    /// Called when a recording ends for any reason — stop button, phone call,
    /// Siri — with the finished file. The file is intact up to that moment.
    var onFinished: ((URL) -> Void)?

    private var recorder: AVAudioRecorder?
    private var ticker: Timer?

    private static let settings: [String: Any] = [
        AVFormatIDKey: kAudioFormatMPEG4AAC,
        AVSampleRateKey: 48_000,
        AVNumberOfChannelsKey: 1,
        AVEncoderBitRateKey: 96_000,
    ]

    private static let stamp: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd-HHmmss"
        return formatter
    }()

    func start(into directory: URL) throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
        try session.setActive(true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appending(path: "memo-\(Self.stamp.string(from: Date())).m4a")
        let recorder = try AVAudioRecorder(url: url, settings: Self.settings)
        recorder.delegate = self
        guard recorder.record() else { throw RecorderError.couldNotStart }
        self.recorder = recorder
        isRecording = true
        elapsed = 0
        // A long note outlives the screen's idle timer, and a phone that
        // sleeps mid-recording comes back to a dark, ambiguous scene. Awake
        // exactly while recording; finish() restores the timer whatever way
        // the recording ends.
        UIApplication.shared.isIdleTimerDisabled = true
        ticker = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.elapsed = self?.recorder?.currentTime ?? 0 }
        }
    }

    func stop() {
        recorder?.stop()  // delivers audioRecorderDidFinishRecording below
    }

    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder,
                                                     successfully flag: Bool) {
        Task { @MainActor in self.finish(recorder) }
    }

    private func finish(_ finished: AVAudioRecorder) {
        guard recorder === finished else { return }
        recorder = nil
        isRecording = false
        UIApplication.shared.isIdleTimerDisabled = false
        ticker?.invalidate()
        ticker = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        onFinished?(finished.url)
    }

    enum RecorderError: Error {
        case couldNotStart
    }
}
