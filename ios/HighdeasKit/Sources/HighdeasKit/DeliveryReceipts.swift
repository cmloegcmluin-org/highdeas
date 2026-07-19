import Foundation

/// A recording the server has taken, kept on the list a moment longer.
public struct DeliveryReceipt: Equatable, Identifiable, Sendable {
    public let fileName: String
    public let recordedAt: Date
    /// When the server's confirmation arrived — what the receipt's short life
    /// is measured from.
    public let deliveredAt: Date

    public var id: String { fileName }

    public init(fileName: String, recordedAt: Date, deliveredAt: Date) {
        self.fileName = fileName
        self.recordedAt = recordedAt
        self.deliveredAt = deliveredAt
    }
}

/// What the phone goes on showing about a recording that has already left it.
///
/// The file is deleted the instant the server confirms receipt — that is what
/// makes the list of files the retry queue — and the row used to go with it. So
/// a thought spoken a moment ago vanished off the screen, and until the desk
/// caught up it was visible nowhere at all. Nothing was ever at risk in that
/// gap (the confirmation only comes after the bytes are on the other machine's
/// disk), but a note disappearing is a fright whatever the truth behind it, and
/// the fright is the thing worth removing.
///
/// A receipt is the row staying put, marked delivered, long enough to be read.
/// It holds nothing durable: losing every receipt to a relaunch costs a moment
/// of reassurance about recordings that are already safe elsewhere, so they are
/// never written down.
public struct DeliveryReceipts: Equatable, Sendable {
    /// How long a delivered recording goes on showing.
    ///
    /// Long enough to look up from the phone and find the note already on the
    /// desk — the desktop draws its outline the moment the recording lands, and
    /// catches up the instant its window is looked at — and short enough that a
    /// morning's dictation doesn't leave a screen of receipts to scroll past.
    public static let linger: TimeInterval = 8

    public private(set) var showing: [DeliveryReceipt]

    public init(showing: [DeliveryReceipt] = []) {
        self.showing = showing
    }

    /// The server took this recording. Re-confirming one already showing keeps
    /// the receipt it has rather than restarting its clock: the fan-out pushes
    /// to every machine at once, and the second one to answer says "already
    /// have it" about a note whose receipt is already counting down.
    public mutating func confirm(_ fileName: String, recordedAt: Date, at now: Date) {
        guard !showing.contains(where: { $0.fileName == fileName }) else { return }
        showing.append(DeliveryReceipt(fileName: fileName, recordedAt: recordedAt,
                                       deliveredAt: now))
    }

    /// Drop the receipts that have been read by now. The caller prunes on the
    /// same beat that redraws the list, so a receipt leaves the screen at the
    /// moment it stops being true rather than at the next thing that happens.
    public mutating func prune(at now: Date) {
        showing.removeAll { now.timeIntervalSince($0.deliveredAt) >= Self.linger }
    }

    /// When the next receipt expires, so the caller can wake up exactly then
    /// instead of leaving one on screen until its slow heartbeat comes round.
    /// Nil when there is nothing showing and so nothing to wake for.
    public func nextExpiry() -> Date? {
        showing.map { $0.deliveredAt.addingTimeInterval(Self.linger) }.min()
    }
}
