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
    /// Fan-out bookkeeping: which machines this flight went to and which have
    /// answered, the refusal to surface if the flight ends with no 2xx, and
    /// when the flight begins — so the UI can stop saying "Uploading…" about a
    /// flight nothing has answered in minutes.
    ///
    /// Begins, not began: a backed-off retry is handed to the system straight
    /// away and told to start later, and until that moment its silence means
    /// nothing. Everything that measures a flight measures from here.
    public var flightPeers: Set<String>
    public var answered: Set<String>
    public var refusalDuringFlight: String?
    public var flightBeginsAt: Date?

    public var id: String { fileName }

    /// Whether the queue has, in effect, learned that no machine is taking
    /// uploads right now: the current flight has gone unanswered for
    /// `silentFor` seconds, or has not been allowed to start yet, or a whole
    /// round already came back with nobody confirming. Being away from every
    /// machine for an afternoon is the app working as designed, so the row
    /// wants to say "will sync later" calmly rather than count retries — and
    /// only this bookkeeping knows that from a flight that's still warm.
    /// A refusal is neither: a machine answered, and what it said is a
    /// problem someone has to fix, so it stays a loud state of its own.
    public func awaitingMachine(at now: Date, silentFor: TimeInterval = 10) -> Bool {
        guard blockedReason == nil else { return false }
        guard inFlight else { return attempts > 0 }
        guard let begins = flightBeginsAt else { return false }
        // Handed over but not started: nobody has taken it and nobody has
        // refused it, which is exactly the calm wait this state is for.
        guard now >= begins else { return true }
        return now.timeIntervalSince(begins) > silentFor
    }

    /// Whether this flight's transfers are actually moving, as opposed to
    /// waiting on a start date the system was given. `inFlight` alone stopped
    /// answering that once a backed-off retry began being handed over early.
    public func isFlying(at now: Date) -> Bool {
        guard inFlight, let begins = flightBeginsAt else { return false }
        return now >= begins
    }

    public init(fileName: String, attempts: Int = 0, notBefore: Date = .distantPast,
                inFlight: Bool = false, blockedReason: String? = nil,
                flightPeers: Set<String> = [], answered: Set<String> = [],
                refusalDuringFlight: String? = nil, flightBeginsAt: Date? = nil) {
        self.fileName = fileName
        self.attempts = attempts
        self.notBefore = notBefore
        self.inFlight = inFlight
        self.blockedReason = blockedReason
        self.flightPeers = flightPeers
        self.answered = answered
        self.refusalDuringFlight = refusalDuringFlight
        self.flightBeginsAt = flightBeginsAt
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

    /// The next upload worth handing over: anything not already in flight.
    /// Oldest first, so the queue drains in recording order.
    ///
    /// A backoff does not hold an entry back here. It rides along on
    /// `notBefore` as the moment the transfer may begin, for the system to
    /// honour — because the app is asleep for most of any wait worth having,
    /// and a backoff only this queue could see would expire unnoticed until
    /// the user next opened the app.
    public func next() -> PendingUpload? {
        pending.first { !$0.inFlight }
    }

    /// A flight begins: the recording is being pushed to each of `peers` at
    /// once — every machine configured, since any one of them taking it is
    /// enough. Naming them (rather than counting them) is what lets a replayed
    /// answer from one machine not stand in for another that hasn't spoken.
    ///
    /// `beginsAt` is when those transfers may actually start: now for an
    /// ordinary push, and the entry's backoff for a retry the system is
    /// holding on the queue's behalf. Never earlier than now — a date already
    /// past is a transfer starting immediately, not one overdue.
    public mutating func markInFlight(_ fileName: String, toward peers: [String],
                                      at now: Date = Date(),
                                      beginningAt beginsAt: Date? = nil) {
        update(fileName) {
            $0.inFlight = true
            $0.flightPeers = Set(peers)
            $0.answered = []
            $0.refusalDuringFlight = nil
            $0.flightBeginsAt = max(now, beginsAt ?? now)
        }
    }

    /// One machine's answer arrives. The first confirmation releases the
    /// recording; failure is declared only when the last machine has answered.
    public mutating func resolve(_ fileName: String, from peer: String,
                                 _ outcome: UploadOutcome, at now: Date) {
        guard let index = pending.firstIndex(where: { $0.fileName == fileName }) else { return }
        // A confirmation is final wherever it comes from and however late it
        // arrives: some computer has the bytes, which is the whole condition for
        // the phone letting go. The other desk gets it from the synced store —
        // the phone is a capture device, not a replica of both machines.
        if case .confirmed = outcome {
            confirmSent(fileName)
            return
        }
        // A failure is only ever news about the flight it belongs to. A dead
        // flight's echo — a cancelled task, a machine answering past the
        // deadline — steers nothing: that entry's course was set when the
        // flight was released.
        guard pending[index].inFlight, pending[index].flightPeers.contains(peer) else { return }
        pending[index].answered.insert(peer)
        if case .blocked(let reason) = outcome {
            pending[index].refusalDuringFlight = reason
        }
        // Failure is declared only once the last machine has answered: one dead
        // peer's fast refusal must not unlock a re-push while another's task is
        // still grinding through the system's background retry.
        guard pending[index].answered.isSuperset(of: pending[index].flightPeers) else { return }
        if let reason = pending[index].refusalDuringFlight {
            block(fileName, reason: reason, at: now)
        } else {
            retryLater(fileName, at: now)
        }
    }

    /// Declare lost any flight silent past `silentFor`, returning it to the
    /// queue under ordinary backoff, and name the released files so the
    /// caller can cancel their tasks. iOS holds a background transfer toward
    /// an unreachable machine indefinitely without a word; treated as still
    /// flying, such a note stays wedged until the next cold launch, because
    /// the pump never re-pushes what is already in flight. A re-push is safe
    /// even if the old transfer later lands — the server dedupes.
    public mutating func releaseStaleFlights(
            at now: Date, silentFor: TimeInterval = 120) -> [String] {
        var released: [String] = []
        for index in pending.indices where pending[index].isFlying(at: now) {
            guard let begins = pending[index].flightBeginsAt,
                  now.timeIntervalSince(begins) > silentFor else { continue }
            takeBackFlight(at: index)
            pending[index].attempts += 1
            pending[index].notBefore = now.addingTimeInterval(
                Self.backoff(afterAttempts: pending[index].attempts))
            released.append(pending[index].fileName)
        }
        return released
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
            $0.flightBeginsAt = nil
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
            $0.flightBeginsAt = nil
            $0.notBefore = now.addingTimeInterval(Self.maximumBackoff)
        }
    }

    /// Make every queued entry due right now, keeping any blocked reason for
    /// the row to show until a fresh answer replaces it. For when the world
    /// changes out from under the backoff — a server URL corrected, a token
    /// fixed — and waiting out a five-minute timer against addresses that no
    /// longer exist would read as "still broken".
    ///
    /// A flight the system has yet to start is addressed to exactly those
    /// stale machines, so it is taken back and named for the caller to cancel.
    /// One already moving is left to land: it may well be aimed at a machine
    /// the new settings still name, and the staleness sweep collects it if not.
    public mutating func expedite(at now: Date) -> [String] {
        var released: [String] = []
        for index in pending.indices where !pending[index].isFlying(at: now) {
            if pending[index].inFlight {  // scheduled, but not started yet
                takeBackFlight(at: index)
                released.append(pending[index].fileName)
            }
            pending[index].notBefore = .distantPast
        }
        return released
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

    /// Return an entry to the queue, forgetting the flight it was on: its
    /// transfers are about to be cancelled, and a dead flight's echoes must
    /// steer nothing. The caller decides what the entry's next attempt costs.
    private mutating func takeBackFlight(at index: Int) {
        pending[index].inFlight = false
        pending[index].flightBeginsAt = nil
        pending[index].flightPeers = []
        pending[index].answered = []
        pending[index].refusalDuringFlight = nil
    }

    private mutating func update(_ fileName: String, _ change: (inout PendingUpload) -> Void) {
        guard let index = pending.firstIndex(where: { $0.fileName == fileName }) else { return }
        change(&pending[index])
    }
}
