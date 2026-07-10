import AVFoundation

/// Playback for one recording still on the phone, scrubbable. AVAudioPlayer
/// under a thin observable shell the Slider can bind to.
@MainActor
final class Player: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var isPlaying = false
    @Published var position: TimeInterval = 0
    @Published private(set) var duration: TimeInterval = 1
    @Published var isScrubbing = false

    private var player: AVAudioPlayer?
    private var ticker: Timer?

    func load(_ url: URL) {
        let loaded = try? AVAudioPlayer(contentsOf: url)
        loaded?.delegate = self
        loaded?.prepareToPlay()
        player = loaded
        duration = max(loaded?.duration ?? 1, 0.01)
        position = 0
    }

    func toggle() {
        guard let player else { return }
        if player.isPlaying {
            player.pause()
            isPlaying = false
        } else {
            try? AVAudioSession.sharedInstance().setCategory(.playback)
            try? AVAudioSession.sharedInstance().setActive(true)
            player.play()
            isPlaying = true
            startTicker()
        }
    }

    /// The Slider drives `position` continuously; the seek lands when the
    /// finger lifts (`editing` turns false).
    func scrub(editing: Bool) {
        isScrubbing = editing
        guard let player, !editing else { return }
        player.currentTime = min(position, duration - 0.05)
        if isPlaying { player.play() }
    }

    func stop() {
        player?.stop()
        player = nil
        isPlaying = false
        ticker?.invalidate()
        ticker = nil
    }

    private func startTicker() {
        ticker?.invalidate()
        ticker = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let player = self.player, !self.isScrubbing else { return }
                self.position = player.currentTime
            }
        }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer,
                                                 successfully flag: Bool) {
        Task { @MainActor in
            self.isPlaying = false
            self.position = 0
            self.ticker?.invalidate()
            self.ticker = nil
        }
    }
}
