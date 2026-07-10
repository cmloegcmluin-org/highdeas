import Foundation
import Testing
@testable import HighdeasKit

private let t0 = Date(timeIntervalSince1970: 1_780_000_000)

@Suite struct UploadQueueTests {
    @Test func enqueueDedupes() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.enqueue("a.m4a")
        #expect(queue.pending.map(\.fileName) == ["a.m4a"])
    }

    @Test func syncFollowsTheDisk() {
        // The files on disk are the truth: entries whose file vanished go,
        // files not yet queued join, existing bookkeeping survives.
        var queue = UploadQueue()
        queue.enqueue("gone.m4a")
        queue.enqueue("kept.m4a")
        queue.retryLater("kept.m4a", at: t0)

        queue.sync(withFiles: ["kept.m4a", "new.m4a"])

        #expect(queue.pending.map(\.fileName) == ["kept.m4a", "new.m4a"])
        #expect(queue.pending[0].attempts == 1)  // sync never resets bookkeeping
    }

    @Test func nextSkipsInFlightAndBackedOff() {
        var queue = UploadQueue()
        queue.enqueue("flying.m4a")
        queue.enqueue("waiting.m4a")
        queue.enqueue("ready.m4a")
        queue.markInFlight("flying.m4a")
        queue.retryLater("waiting.m4a", at: t0)

        #expect(queue.next(at: t0)?.fileName == "ready.m4a")
        // Once the backoff passes, the older entry is preferred again.
        #expect(queue.next(at: t0.addingTimeInterval(600))?.fileName == "waiting.m4a")
    }

    @Test func nextIsEmptyWhenEverythingWaits() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a")
        #expect(queue.next(at: t0) == nil)
    }

    @Test func confirmSentRemovesTheEntry() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.confirmSent("a.m4a")
        #expect(queue.pending.isEmpty)
    }

    @Test func retryLaterBacksOffAndClearsInFlight() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a")

        queue.retryLater("a.m4a", at: t0)

        let entry = queue.pending[0]
        #expect(entry.attempts == 1)
        #expect(!entry.inFlight)
        #expect(entry.notBefore == t0.addingTimeInterval(5))
    }

    @Test func blockSurfacesTheReasonAndWaitsTheCeiling() {
        // A 401 won't be fixed by time; the row shows why, and the queue only
        // nudges at the slowest cadence until Settings change.
        var queue = UploadQueue()
        queue.enqueue("a.m4a")

        queue.block("a.m4a", reason: "bad token", at: t0)

        let entry = queue.pending[0]
        #expect(entry.blockedReason == "bad token")
        #expect(entry.notBefore == t0.addingTimeInterval(UploadQueue.maximumBackoff))
    }

    @Test func retryAfterBlockClearsTheReason() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.block("a.m4a", reason: "bad token", at: t0)

        queue.retryLater("a.m4a", at: t0)

        #expect(queue.pending[0].blockedReason == nil)
    }

    @Test func backoffDoublesToACeiling() {
        #expect(UploadQueue.backoff(afterAttempts: 0) == 0)
        #expect(UploadQueue.backoff(afterAttempts: 1) == 5)
        #expect(UploadQueue.backoff(afterAttempts: 2) == 10)
        #expect(UploadQueue.backoff(afterAttempts: 3) == 20)
        #expect(UploadQueue.backoff(afterAttempts: 7) == 300)
        #expect(UploadQueue.backoff(afterAttempts: 50) == 300)  // no overflow
    }
}
