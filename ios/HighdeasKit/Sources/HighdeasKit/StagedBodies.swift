import Foundation

/// One assembled multipart body found in the uploader's staging folder, as much
/// of it as the decision needs: what it is called, and when it was written —
/// or nothing, if the filesystem wouldn't say.
public struct StagedBody: Equatable, Sendable {
    public let name: String
    public let modified: Date?

    public init(name: String, modified: Date?) {
        self.name = name
        self.modified = modified
    }
}

/// Housekeeping for the folder each fan-out stages its multipart bodies in.
///
/// A body is deleted when its transfer calls back, which is every transfer that
/// ever answers. The ones that don't answer leave theirs: iOS holds a background
/// task toward a machine it can't reach without a word, and the entry that would
/// eventually have cancelled it left the queue the moment a *different* machine
/// confirmed the recording — the note is delivered, so nothing is watching its
/// siblings any more. Nine had collected on the phone by 2026-08-08, the oldest
/// from ten days before. Caches is purgeable by iOS, so this is untidiness
/// rather than a risk to anything, which is why the sweep runs once at launch
/// and no more.
///
/// The rule is the one the server's `_sweep_stale_staging` uses on its own
/// `.part` leftovers, at the phone's timescale.
public enum StagedBodies {
    /// How long a body may sit before a sweep presumes its transfer is never
    /// going to finish. A day is generous on purpose: the queue's own patience
    /// with a silent flight is two minutes, so anything this old belongs to a
    /// flight that was given up on and re-pushed long ago, or to no flight at
    /// all. Nothing that reaches this age is still expected to land.
    public static let staleAfter: TimeInterval = 86_400

    /// What a staged body is called, so the sweep matches what `push` writes
    /// by construction rather than by both spelling it the same.
    public static let suffix = ".body"

    /// The leftovers worth deleting, named rather than counted so the caller
    /// removes exactly these and nothing else it happened to find in there.
    ///
    /// A *fresh* body is never one of them. It belongs to a transfer under way,
    /// or to the instant in `push` between the body being written and the task
    /// existing to stream it — and a body deleted out from under either is a
    /// delivery that was going to happen and now won't.
    public static func stale(among leftovers: [StagedBody], at now: Date) -> [String] {
        leftovers.filter { leftover in
            guard leftover.name.hasSuffix(suffix), let modified = leftover.modified
            else { return false }
            return now.timeIntervalSince(modified) > staleAfter
        }.map(\.name)
    }
}
