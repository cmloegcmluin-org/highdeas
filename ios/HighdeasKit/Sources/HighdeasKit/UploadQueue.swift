import Foundation

/// One recording waiting to reach the server. The file on disk is the durable
/// truth — a recording exists on the phone exactly until the server confirms
/// receipt — so this struct carries only the retry bookkeeping that is allowed
/// to reset on relaunch.
public struct PendingUpload: Equatable, Identifiable, Sendable {
    public let fileName: String
    public var attempts: Int
    /// Earliest moment the next attempt may start (backoff).
    public var notBefore: Date
    public var inFlight: Bool
    /// Why the server refused, when it did (bad token, rejected suffix…).
    /// Shown on the row; a blocked upload still retries, slowly, so fixing
    /// the token in Settings heals the queue without any per-row action.
    public var blockedReason: String?
    /// Fan-out bookkeeping: how many machines this flight is still waiting
    /// on, the refusal to surface if the flight ends without a 2xx, and when
    /// the flight began — so the UI can stop saying "Uploading…" about a
    /// flight nothing has answered in minutes.
    public var outcomesAwaited: Int
    public var refusalDuringFlight: String?
    public var flightStartedAt: Date?

    public var id: String { fileName }

    /// Whether the queue has, in effect, learned that no machine is taking
    /// uploads right now: the current flight has gone unanswered for
    /// `silentFor` seconds, or a whole round already came back with nobody
    /// confirming and the entry is waiting out its backoff. Being away from
    /// every machine for an afternoon is the app working as designed, so the
    /// row wants to say "will sync later" calmly rather than count retries —
    /// and only this bookkeeping knows that from a flight that's still warm.
    /// A refusal is neither: a machine answered, and what it said is a
    /// problem someone has to fix, so it stays a loud state of its own.
    public func awaitingMachine(at now: Date, silentFor: TimeInterval = 30) -> Bool {
        if inFlight {
            guard let started = flightStartedAt else { return false }
            return now.timeIntervalSince(started) > silentFor
        }
        return blockedReason == nil && attempts > 0
    }

    public init(fileName: String, attempts: Int = 0, notBefore: Date = .distantPast,
                inFlight: Bool = false, blockedReason: String? = nil,
                outcomesAwaited: Int = 0, refusalDuringFlight: String? = nil,
                flightStartedAt: Date? = nil) {
        self.fileName = fileName
        self.attempts = attempts
        self.notBefore = notBefore
        self.inFlight = inFlight
        self.blockedReason = blockedReason
        self.outcomesAwaited = outcomesAwaited
        self.refusalDuringFlight = refusalDuringFlight
        self.flightStartedAt = flightStartedAt
    }
}

/// The retry queue's state machine, pure and synchronous: what to try next,
/// and how each outcome changes the queue. The caller owns time, disk, and
/// network; this owns the rules.
public struct UploadQueue: Equatable, Sendable {
    public private(set) var pending: [PendingUpload]

    public init(pending: [PendingUpload] = []) {
        self.pending = pending
    }

    /// Add a recording to the queue; re-adding one already queued is a no-op
    /// (the disk scan and a fresh stop() can both announce the same file).
    public mutating func enqueue(_ fileName: String) {
        guard !pending.contains(where: { $0.fileName == fileName }) else { return }
        pending.append(PendingUpload(fileName: fileName))
    }

    /// Forget entries whose file no longer exists, and adopt files not yet
    /// queued — the disk is the truth the queue follows.
    public mutating func sync(withFiles fileNames: [String]) {
        let present = Set(fileNames)
        pending.removeAll { !present.contains($0.fileName) }
        for name in fileNames { enqueue(name) }
    }

    /// The next upload worth attempting: not already in flight, past its
    /// backoff. Oldest first, so the queue drains in recording order.
    public func next(at now: Date) -> PendingUpload? {
        pending.first { !$0.inFlight && $0.notBefore <= now }
    }

    /// A flight begins: the recording is being pushed to `expecting` machines
    /// at once (every configured peer — the shared store dedupes, so whichever
    /// machine answers second just says "already have it").
    public mutating func markInFlight(_ fileName: String, expecting: Int = 1, at now: Date = Date()) {
        update(fileName) {
            $0.inFlight = true
            $0.outcomesAwaited = expecting
            $0.refusalDuringFlight = nil
            $0.flightStartedAt = now
        }
    }

    /// One machine's answer arrives. The first confirmation wins immediately;
    /// failure is declared only when the last machine has answered — one dead
    /// peer's fast refusal must not unlock a re-push while another's task is
    /// still grinding through the system's background retry.
    public mutating func resolve(_ fileName: String, _ outcome: UploadOutcome, at now: Date) {
        guard let index = pending.firstIndex(where: { $0.fileName == fileName }) else { return }
        switch outcome {
        case .confirmed:
            confirmSent(fileName)
        case .blocked(let reason):
            pending[index].refusalDuringFlight = reason
            fallthrough
        case .retriable:
            pending[index].outcomesAwaited -= 1
            guard pending[index].outcomesAwaited <= 0 else { return }
            if let reason = pending[index].refusalDuringFlight {
                block(fileName, reason: reason, at: now)
            } else {
                retryLater(fileName, at: now)
            }
        }
    }

    /// The server confirmed receipt (2xx): the entry leaves the queue. The
    /// caller deletes the file — in that order, so a crash in between leaves
    /// a duplicate upload (harmless, the server dedupes) rather than a lost one.
    public mutating func confirmSent(_ fileName: String) {
        pending.removeAll { $0.fileName == fileName }
    }

    /// Transport failed or the server 5xx'd: back off and try again.
    public mutating func retryLater(_ fileName: String, at now: Date) {
        update(fileName) {
            $0.attempts += 1
            $0.inFlight = false
            $0.blockedReason = nil
            $0.flightStartedAt = nil
            $0.notBefore = now.addingTimeInterval(Self.backoff(afterAttempts: $0.attempts))
        }
    }

    /// The server refused (bad token, rejected file): keep the recording,
    /// surface why, and retry only at the slowest cadence — a config fix,
    /// not time, is what will heal this.
    public mutating func block(_ fileName: String, reason: String, at now: Date) {
        update(fileName) {
            $0.attempts += 1
            $0.inFlight = false
            $0.blockedReason = reason
            $0.flightStartedAt = nil
            $0.notBefore = now.addingTimeInterval(Self.maximumBackoff)
        }
    }

    public static let maximumBackoff: TimeInterval = 300

    /// 5s, 10s, 20s… doubling to a 5-minute ceiling. Fast enough that a memo
    /// recorded in a dead spot lands moments after the phone finds Wi-Fi,
    /// slow enough to never hammer the PC.
    public static func backoff(afterAttempts attempts: Int) -> TimeInterval {
        guard attempts > 0 else { return 0 }
        let doubled = 5 * pow(2, Double(attempts - 1))
        return min(maximumBackoff, doubled)
    }

    private mutating func update(_ fileName: String, _ change: (inout PendingUpload) -> Void) {
        guard let index = pending.firstIndex(where: { $0.fileName == fileName }) else { return }
        change(&pending[index])
    }
}
