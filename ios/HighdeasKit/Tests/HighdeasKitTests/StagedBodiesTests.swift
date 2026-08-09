import Foundation
import Testing
@testable import HighdeasKit

private let t0 = Date(timeIntervalSince1970: 1_780_000_000)

@Suite struct StagedBodiesTests {
    @Test func aBodyLeftOverFromDaysAgoIsSwept() {
        // The one observed on the phone: nine of these had piled up, the oldest
        // ten days old, because the task that would have deleted it never
        // called back.
        let old = StagedBody(name: "memo-2026-07-29-165533.m4a.5EC77170.body",
                             modified: t0.addingTimeInterval(-StagedBodies.staleAfter - 1))

        #expect(StagedBodies.stale(among: [old], at: t0) == [old.name])
    }

    @Test func aFreshBodyIsLeftAlone() {
        // It belongs to a transfer under way — or to the instant in `push`
        // between the body being written and the task existing to stream it.
        // Deleting either would break a delivery that was going to happen.
        let justWritten = StagedBody(name: "memo.m4a.A1.body", modified: t0)
        let hoursOld = StagedBody(name: "memo.m4a.B2.body",
                                  modified: t0.addingTimeInterval(-StagedBodies.staleAfter + 1))

        #expect(StagedBodies.stale(among: [justWritten, hoursOld], at: t0).isEmpty)
    }

    @Test func onlyStagedBodiesAreSwept() {
        // The sweep names what it deletes rather than emptying a folder by
        // its age, so anything that turns up in there and isn't ours — an
        // iOS artefact, a future staging file — outlives it.
        let ours = StagedBody(name: "memo.m4a.C3.body", modified: t0.addingTimeInterval(-604_800))
        let stranger = StagedBody(name: ".DS_Store", modified: t0.addingTimeInterval(-604_800))

        #expect(StagedBodies.stale(among: [ours, stranger], at: t0) == [ours.name])
    }

    @Test func aBodyTheFilesystemWouldNotDateIsLeftAlone() {
        // No date is not the same as an old date. A leftover nobody can age is
        // one the sweep has no grounds to call finished with, and the cost of
        // guessing wrong runs one way: keeping it wastes a few megabytes of
        // purgeable cache, deleting it can pull the body out from under a
        // transfer that was still going to land.
        let undated = StagedBody(name: "memo.m4a.D4.body", modified: nil)

        #expect(StagedBodies.stale(among: [undated], at: t0).isEmpty)
    }
}
