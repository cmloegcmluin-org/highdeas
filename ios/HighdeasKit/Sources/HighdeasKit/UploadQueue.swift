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
    /// when the flight began — so the UI can stop saying "Uploading…" about a
    /// flight nothing has answered in minutes.
    public var flightPeers: Set<String>
    public var answered: Set<String>
    public var refusalDuringFlight: String?
    public var flightStartedAt: Date?
    /// Which machines are known to hold this recording. It outlives the flight
    /// that earned it: a peer that took the file in one round is not pushed to
    /// again, and the recording stays on the phone until every machine is in
    /// here. That is the whole point — the phone is the only device present at
    /// both ends of a trip, so it, not Syncthing, is what carries a note to a
    /// machine that was asleep when the note was spoken.
    public var confirmedBy: Set<String>
    /// When the first machine took it, and so when the patience clock starts
    /// for the machines that haven't (see `releaseLongUndelivered`).
    public var firstConfirmedAt: Date?

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
    public func awaitingMachine(at now: Date, silentFor: TimeInterval = 10) -> Bool {
        if inFlight {
            guard let started = flightStartedAt else { return false }
            return now.timeIntervalSince(started) > silentFor
        }
        return blockedReason == nil && attempts > 0
    }

    public init(fileName: String, attempts: Int = 0, notBefore: Date = .distantPast,
                inFlight: Bool = false, blockedReason: String? = nil,
                flightPeers: Set<String> = [], answered: Set<String> = [],
                refusalDuringFlight: String? = nil, flightStartedAt: Date? = nil,
                confirmedBy: Set<String> = [], firstConfirmedAt: Date? = nil) {
        self.fileName = fileName
        self.attempts = attempts
        self.notBefore = notBefore
        self.inFlight = inFlight
        self.blockedReason = blockedReason
        self.flightPeers = flightPeers
        self.answered = answered
        self.refusalDuringFlight = refusalDuringFlight
        self.flightStartedAt = flightStartedAt
        self.confirmedBy = confirmedBy
        self.firstConfirmedAt = firstConfirmedAt
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

    /// A flight begins: the recording is being pushed to each of `peers` at
    /// once. The caller passes only the machines that don't have it yet, so a
    /// second round after a partial delivery is addressed to the stragglers
    /// alone — the machine that already answered is neither asked again nor
    /// waited for.
    public mutating func markInFlight(_ fileName: String, toward peers: [String],
                                      at now: Date = Date()) {
        update(fileName) {
            $0.inFlight = true
            $0.flightPeers = Set(peers)
            $0.answered = []
            $0.refusalDuringFlight = nil
            $0.flightStartedAt = now
        }
    }

    /// One machine's answer arrives. A confirmation is recorded against that
    /// machine and nothing more: the recording leaves the phone only once every
    /// machine in the flight has taken it. Failure is likewise declared only
    /// when the last machine has answered — one dead peer's fast refusal must
    /// not unlock a re-push while another's task is still grinding through the
    /// system's background retry.
    public mutating func resolve(_ fileName: String, from peer: String,
                                 _ outcome: UploadOutcome, at now: Date) {
        guard let index = pending.firstIndex(where: { $0.fileName == fileName }) else { return }
        // A confirmation is a fact about that machine — it has the bytes — and
        // stays true however late it arrives, including from a flight already
        // given up on. A failure is only ever news about the flight it belongs
        // to: a dead flight's echo (a cancelled task, a machine answering past
        // the deadline) steers nothing, because that entry's course was set
        // when the flight was released.
        if case .confirmed = outcome {
            pending[index].confirmedBy.insert(peer)
            if pending[index].firstConfirmedAt == nil {
                pending[index].firstConfirmedAt = now
            }
        }
        var flightIsOver = false
        if pending[index].inFlight, pending[index].flightPeers.contains(peer) {
            pending[index].answered.insert(peer)
            if case .blocked(let reason) = outcome {
                pending[index].refusalDuringFlight = reason
            }
            flightIsOver = pending[index].answered.isSuperset(of: pending[index].flightPeers)
        }
        // Everyone it was last addressed to has it: the phone is done carrying it.
        if !pending[index].flightPeers.isEmpty,
           pending[index].flightPeers.isSubset(of: pending[index].confirmedBy) {
            confirmSent(fileName)
        } else if flightIsOver {
            if let reason = pending[index].refusalDuringFlight {
                block(fileName, reason: reason, at: now)
            } else {
                retryLater(fileName, at: now)
            }
        }
    }

    /// The machines that still owe this recording a home — what the next flight
    /// is addressed to, given everything currently configured.
    public func peersStillOwed(_ fileName: String, of peers: [String]) -> [String] {
        guard let entry = pending.first(where: { $0.fileName == fileName }) else { return [] }
        return peers.filter { !entry.confirmedBy.contains($0) }
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
        for index in pending.indices where pending[index].inFlight {
            guard let started = pending[index].flightStartedAt,
                  now.timeIntervalSince(started) > silentFor else { continue }
            pending[index].inFlight = false
            pending[index].attempts += 1
            pending[index].flightStartedAt = nil
            // flightPeers outlives the flight: it is the record of who this
            // recording is owed to, and a confirmation that trickles in after
            // the release still has to be able to complete the set.
            pending[index].answered = []
            pending[index].refusalDuringFlight = nil
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

    /// Make every queued entry due right now, keeping any blocked reason for
    /// the row to show until a fresh answer replaces it. For when the world
    /// changes out from under the backoff — a server URL corrected, a token
    /// fixed — and waiting out a five-minute timer against addresses that no
    /// longer exist would read as "still broken".
    public mutating func expedite() {
        for index in pending.indices where !pending[index].inFlight {
            pending[index].notBefore = .distantPast
        }
    }

    /// How long a recording that at least one machine already holds goes on
    /// waiting for the rest.
    ///
    /// Without a limit, "keep it until every machine has it" means a machine
    /// that is never coming back — a laptop sold, an address mistyped in
    /// Settings — pins every recording on the phone forever, and the only cure
    /// is noticing and deleting the line. A week is longer than any trip that
    /// ends at one of these desks, and the note is not at risk meanwhile: some
    /// machine has had it since the clock started, so letting go costs the
    /// second copy, never the note.
    public static let deliveryPatience: TimeInterval = 7 * 24 * 60 * 60

    /// Let go of recordings that one machine took and the others never came
    /// for. Returns their names so the caller can delete the files.
    public mutating func releaseLongUndelivered(
            at now: Date, patience: TimeInterval = deliveryPatience) -> [String] {
        let given = pending.filter {
            guard let since = $0.firstConfirmedAt else { return false }
            return now.timeIntervalSince(since) >= patience
        }.map(\.fileName)
        pending.removeAll { given.contains($0.fileName) }
        return given
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
