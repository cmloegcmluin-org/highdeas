import Foundation
import Testing
@testable import HighdeasKit

private let t0 = Date(timeIntervalSince1970: 1_780_000_000)

/// The machines a flight is addressed to. Endpoints are identified by their
/// upload URL, which is what the app has to hand and what stays stable across
/// relaunches.
let pc = "http://192.168.1.23:5055/upload"
let mac = "http://192.168.1.44:5055/upload"
let spare = "http://192.168.1.99:5055/upload"

/// The first `count` of them, for tests that only care how many answered.
func machines(_ count: Int) -> [String] {
    Array([pc, mac, spare].prefix(count))
}

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

    @Test func nextSkipsOnlyWhatIsAlreadyInFlight() {
        // A backoff is not a reason to hold an entry back: it travels with the
        // entry as the moment its transfer may begin, for the system to honour
        // while the app is asleep. Waiting it out in here would mean waiting
        // for the user to open the app.
        var queue = UploadQueue()
        queue.enqueue("flying.m4a")
        queue.enqueue("waiting.m4a")
        queue.markInFlight("flying.m4a", toward: [pc])
        queue.retryLater("waiting.m4a", at: t0)

        let handed = queue.next()
        #expect(handed?.fileName == "waiting.m4a")
        #expect(handed?.notBefore == t0.addingTimeInterval(5))
    }

    @Test func nextIsEmptyWhenEverythingIsInFlight() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: [pc])
        #expect(queue.next() == nil)
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
        queue.markInFlight("a.m4a", toward: [pc])

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

// MARK: - Fan-out: one recording pushed to every machine at once

@Suite struct FanOutTests {
    let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func queued(_ name: String = "a.m4a", expecting peers: Int) -> UploadQueue {
        var queue = UploadQueue()
        queue.enqueue(name)
        queue.markInFlight(name, toward: machines(peers))
        return queue
    }

    @Test func aFlightStaysInFlightUntilEveryPeerHasAnswered() {
        var queue = queued(expecting: 2)

        queue.resolve("a.m4a", from: pc, .retriable, at: now)

        // One dead machine must not unlock a re-push while the other's task
        // is still grinding in the system's background retry.
        #expect(queue.next() == nil)
        #expect(queue.pending.first?.inFlight == true)
    }

    @Test func aFlightFailsOnlyWhenTheLastPeerFails() {
        var queue = queued(expecting: 2)

        queue.resolve("a.m4a", from: pc, .retriable, at: now)
        queue.resolve("a.m4a", from: mac, .retriable, at: now)

        let entry = queue.pending.first
        #expect(entry?.inFlight == false)
        #expect(entry?.attempts == 1)  // one flight, not one per peer
        #expect(entry?.notBefore ?? .distantPast > now)
    }

    @Test func twoAnswersFromTheSameMachineAreOneAnswer() {
        // The count that ends a flight is of machines, not of callbacks: a
        // background session can replay an outcome, and a replayed refusal must
        // not stand in for the machine that hasn't spoken yet.
        var queue = queued(expecting: 2)

        queue.resolve("a.m4a", from: pc, .retriable, at: now)
        queue.resolve("a.m4a", from: pc, .retriable, at: now)

        #expect(queue.pending.first?.inFlight == true)
    }

    @Test func aFailureFromAMachineTheFlightNeverWentToIsIgnored() {
        // Settings changed mid-flight, or a task from the previous round landed
        // late: either way that refusal is news about a different flight, and
        // must not stand in for the machine this one is still waiting on.
        var queue = queued(expecting: 1)

        queue.resolve("a.m4a", from: spare, .retriable, at: now)

        #expect(queue.pending.first?.inFlight == true)
        #expect(queue.pending.first?.attempts == 0)
    }

    @Test func aConfirmationCountsWhoeverItCameFrom() {
        // Unlike a refusal: a 2xx means a computer holds the bytes, which is
        // true whether or not this flight was addressed to that one.
        var queue = queued(expecting: 1)

        queue.resolve("a.m4a", from: spare, .confirmed, at: now)

        #expect(queue.pending.isEmpty)
    }

    @Test func aLateOutcomeAfterConfirmationIsANoOp() {
        var queue = queued(expecting: 2)
        queue.resolve("a.m4a", from: pc, .confirmed, at: now)

        queue.resolve("a.m4a", from: mac, .retriable, at: now)

        #expect(queue.pending.isEmpty)
    }

    @Test func aRefusalIsRememberedEvenWhenTheOtherPeerMerelyFailed() {
        // One machine 401s (config problem worth words), the other is off.
        var queue = queued(expecting: 2)

        queue.resolve("a.m4a", from: pc,
                      .blocked("The server rejected the upload token — check Settings."), at: now)
        queue.resolve("a.m4a", from: mac, .retriable, at: now)

        let entry = queue.pending.first
        #expect(entry?.blockedReason?.contains("token") == true)
        #expect(entry?.notBefore == now.addingTimeInterval(UploadQueue.maximumBackoff))
    }

    @Test func singlePeerFlightsBehaveAsTheyAlwaysHave() {
        var queue = queued(expecting: 1)

        queue.resolve("a.m4a", from: pc, .retriable, at: now)

        let entry = queue.pending.first
        #expect(entry?.inFlight == false)
        #expect(entry?.attempts == 1)
    }
}

// MARK: - Leaving the phone as soon as a computer has it

/// A recording exists on the phone exactly until a computer has it. Not until
/// every computer has it: the phone is a capture device, not a replica. Once a
/// note is on a machine it is inside the synced store, and the other desk is
/// that store's problem, not something the user should watch a row about.
@Suite struct FirstComputerTests {
    let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func flying(_ name: String = "a.m4a", toward peers: [String]) -> UploadQueue {
        var queue = UploadQueue()
        queue.enqueue(name)
        queue.markInFlight(name, toward: peers, at: now)
        return queue
    }

    @Test func theFirstComputerToTakeItReleasesTheRecording() {
        var queue = flying(toward: [pc, mac])

        queue.resolve("a.m4a", from: pc, .confirmed, at: now)

        #expect(queue.pending.isEmpty)
    }

    @Test func oneMachineFailingLeavesTheRecordingWithTheOther() {
        // Nothing is released on a refusal: a note in zero places is the one
        // outcome the queue exists to prevent.
        var queue = flying(toward: [pc, mac])

        queue.resolve("a.m4a", from: pc, .retriable, at: now)

        #expect(queue.pending.count == 1)
    }

    @Test func aRoundNoMachineTookKeepsTheRecording() {
        var queue = flying(toward: [pc, mac])

        queue.resolve("a.m4a", from: pc, .retriable, at: now)
        queue.resolve("a.m4a", from: mac, .retriable, at: now)

        #expect(queue.pending.count == 1)
        #expect(queue.pending.first?.inFlight == false)   // free to be tried again
    }
}

// MARK: - Parsing the Settings screen's list of machines

@Suite struct EndpointListTests {
    @Test func anEndpointIsIdentifiedByTheAddressItPostsTo() {
        // The queue records deliveries against this string, so it has to be the
        // same across relaunches and different between machines. The upload URL
        // is both — and is what the Settings line already is.
        let endpoint = UploadEndpoint(serverURL: "http://192.168.1.23:5055", token: "tok")

        #expect(endpoint?.key == "http://192.168.1.23:5055/upload")
    }

    @Test func oneEndpointPerLineTrimmedAndValidated() {
        let endpoints = UploadEndpoint.list(
            from: " http://192.168.1.23:5055 \n\nhttp://mac.tail1234.ts.net:5055\nnot a url\n",
            token: "tok")

        #expect(endpoints.map(\.uploadURL.absoluteString) == [
            "http://192.168.1.23:5055/upload",
            "http://mac.tail1234.ts.net:5055/upload",
        ])
    }

    @Test func anEmptyTokenMeansNoEndpointsAtAll() {
        #expect(UploadEndpoint.list(from: "http://192.168.1.23:5055", token: " ").isEmpty)
    }
}

// MARK: - Telling the truth about a flight nothing has answered

@Suite struct StaleFlightTests {
    let start = Date(timeIntervalSince1970: 1_800_000_000)

    @Test func aFlightRemembersWhenItBegan() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")

        queue.markInFlight("a.m4a", toward: machines(3), at: start)

        #expect(queue.pending.first?.flightBeginsAt == start)
    }

    @Test func aRetryRemembersWhenTheSystemWillStartIt() {
        // The transfers of a backed-off retry are handed over at once but told
        // to begin later. The clock a flight is measured against is that later
        // moment: nothing has gone quiet yet, because nothing has spoken yet.
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        let due = start.addingTimeInterval(300)

        queue.markInFlight("a.m4a", toward: machines(2), at: start, beginningAt: due)

        #expect(queue.pending.first?.flightBeginsAt == due)
    }

    @Test func aFlightThatHasNotBegunIsNotStale() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(2), at: start,
                           beginningAt: start.addingTimeInterval(300))

        // Well past the staleness window measured from the hand-over, but the
        // transfer has not started, so there is nothing to give up on yet.
        #expect(queue.releaseStaleFlights(at: start.addingTimeInterval(200)).isEmpty)
        #expect(queue.releaseStaleFlights(at: start.addingTimeInterval(421))
                == ["a.m4a"])
    }

    @Test func resolvingClearsTheFlightClock() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(1), at: start)

        queue.resolve("a.m4a", from: pc, .retriable, at: start.addingTimeInterval(5))

        #expect(queue.pending.first?.flightBeginsAt == nil)
    }
}

// MARK: - Knowing when no machine is around

/// Recording an afternoon away from every machine is the app working as
/// designed, not an incident. These pin down when an entry may say so:
/// a flight gone unanswered for a short while, or a whole round already
/// come back empty — but never a refusal, which is a person's problem to fix.
@Suite struct AwaitingMachineTests {
    let start = Date(timeIntervalSince1970: 1_800_000_000)

    private func entry(in queue: UploadQueue) -> PendingUpload { queue.pending[0] }

    @Test func aFreshFlightIsStillJustUploading() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(2), at: start)

        #expect(!entry(in: queue).awaitingMachine(at: start.addingTimeInterval(5)))
    }

    @Test func aFlightNothingAnswersGoesToAwaitingAMachine() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(2), at: start)

        #expect(entry(in: queue).awaitingMachine(at: start.addingTimeInterval(11)))
    }

    @Test func aRoundThatCameBackEmptyWaitsAsAwaitingAMachineNotAsACountdown() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(2), at: start)
        queue.resolve("a.m4a", from: pc, .retriable, at: start.addingTimeInterval(1))
        queue.resolve("a.m4a", from: mac, .retriable, at: start.addingTimeInterval(2))

        #expect(entry(in: queue).awaitingMachine(at: start.addingTimeInterval(3)))
    }

    @Test func aRefusalIsNotAMissingMachine() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(1), at: start)
        queue.resolve("a.m4a", from: pc, .blocked("Server refused (401)."), at: start.addingTimeInterval(1))

        #expect(!entry(in: queue).awaitingMachine(at: start.addingTimeInterval(60)))
    }

    @Test func aRecordingNeverYetTriedIsNotAwaitingAMachine() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")

        #expect(!entry(in: queue).awaitingMachine(at: start))
    }

    @Test func aRetryTheSystemIsHoldingForLaterIsAwaitingAMachine() {
        // Handed over but not started yet. "Uploading…" would be a lie about a
        // transfer that has not begun, and the calm wait is the truth: a round
        // already came back with nobody taking it.
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(2), at: start)
        queue.resolve("a.m4a", from: pc, .retriable, at: start)
        queue.resolve("a.m4a", from: mac, .retriable, at: start)
        queue.markInFlight("a.m4a", toward: machines(2), at: start,
                           beginningAt: start.addingTimeInterval(300))

        #expect(entry(in: queue).awaitingMachine(at: start.addingTimeInterval(1)))
    }

    @Test func aRefusalHeldForLaterIsStillARefusal() {
        // A blocked entry is re-handed over on the slowest cadence like any
        // other, but what the row has to say is still the refusal — not the
        // calm wait that means nobody answered.
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.block("a.m4a", reason: "Server refused (401).", at: start)
        queue.markInFlight("a.m4a", toward: machines(1), at: start,
                           beginningAt: start.addingTimeInterval(300))

        #expect(!entry(in: queue).awaitingMachine(at: start.addingTimeInterval(1)))
    }
}

// MARK: - Which flights are actually moving

/// `inFlight` stopped meaning "moving now" once a backed-off retry began being
/// handed over early and told to start later. These pin the difference, which
/// is what the row's "Uploading…" hangs on.
@Suite struct FlyingTests {
    let start = Date(timeIntervalSince1970: 1_800_000_000)

    @Test func aFlightThatHasBegunIsFlying() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(1), at: start)

        #expect(queue.pending[0].isFlying(at: start))
    }

    @Test func aFlightHeldForLaterIsNotFlyingYet() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(1), at: start,
                           beginningAt: start.addingTimeInterval(300))

        #expect(!queue.pending[0].isFlying(at: start.addingTimeInterval(1)))
        #expect(queue.pending[0].isFlying(at: start.addingTimeInterval(301)))
    }

    @Test func anEntryWithNoFlightIsNotFlying() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")

        #expect(!queue.pending[0].isFlying(at: start))
    }
}

// MARK: - Retrying now because the settings changed

@Suite struct ExpediteTests {
    let start = Date(timeIntervalSince1970: 1_800_000_000)

    @Test func expediteMakesABackedOffEntryDueImmediately() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: [pc], at: start)
        queue.resolve("a.m4a", from: pc, .retriable, at: start)  // backoff pushes notBefore out

        _ = queue.expedite(at: start)

        #expect(queue.next()?.notBefore == .distantPast)
    }

    @Test func expediteKeepsABlockedReasonButRetriesAnyway() {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: [pc], at: start)
        queue.resolve("a.m4a", from: pc, .blocked("Server refused (401)."), at: start)

        _ = queue.expedite(at: start)

        // Due now — a fixed token deserves an immediate answer — but the row
        // keeps saying why it was stuck until that answer arrives.
        #expect(queue.next()?.notBefore == .distantPast)
        #expect(queue.pending[0].blockedReason == "Server refused (401).")
    }

    @Test func expediteTakesBackAFlightTheSystemHasNotStarted() {
        // Its transfers are addressed to the machines the old settings named,
        // and they have not run yet: waiting out five minutes to find out they
        // point nowhere would read as "still broken". Named back so the caller
        // can cancel them.
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: [pc], at: start,
                           beginningAt: start.addingTimeInterval(300))

        #expect(queue.expedite(at: start) == ["a.m4a"])
        #expect(queue.next()?.notBefore == .distantPast)
        #expect(queue.pending[0].flightBeginsAt == nil)
    }

    @Test func expediteLeavesALiveFlightAlone() {
        // Already moving, and possibly toward a machine the new settings still
        // name. Let it land; the staleness sweep collects it if it doesn't.
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: [pc], at: start)

        #expect(queue.expedite(at: start).isEmpty)

        #expect(queue.next() == nil)  // still in flight, not re-pushed
    }
}

// MARK: - Giving up on a flight the system has quietly parked

/// iOS can hold a background transfer toward an unreachable machine forever
/// without a word. Left alone, that wedges the note until the next cold
/// launch: still "in flight", so the pump never re-pushes it. These pin the
/// escape: a flight silent past the deadline returns to the queue under
/// ordinary backoff, and only a confirmation may speak for it afterwards.
@Suite struct StaleFlightReleaseTests {
    let start = Date(timeIntervalSince1970: 1_800_000_000)

    private func stuckQueue() -> UploadQueue {
        var queue = UploadQueue()
        queue.enqueue("a.m4a")
        queue.markInFlight("a.m4a", toward: machines(2), at: start)
        return queue
    }

    @Test func aSilentFlightPastTheDeadlineReturnsToTheQueue() {
        var queue = stuckQueue()

        let released = queue.releaseStaleFlights(at: start.addingTimeInterval(121))

        #expect(released == ["a.m4a"])
        let entry = queue.pending[0]
        #expect(!entry.inFlight)
        #expect(entry.attempts == 1)
        #expect(entry.notBefore == start.addingTimeInterval(121 + 5))
        #expect(queue.next()?.fileName == "a.m4a")
    }

    @Test func aWarmFlightIsLeftAlone() {
        var queue = stuckQueue()

        #expect(queue.releaseStaleFlights(at: start.addingTimeInterval(60)).isEmpty)
        #expect(queue.pending[0].inFlight)
    }

    @Test func aDeadFlightsFailureEchoSteersNothing() {
        var queue = stuckQueue()
        _ = queue.releaseStaleFlights(at: start.addingTimeInterval(121))
        let released = queue.pending[0]

        // The cancelled tasks (and any machine answering after the deadline)
        // still echo through the delegate; the entry's course is already set.
        queue.resolve("a.m4a", from: pc, .retriable, at: start.addingTimeInterval(122))
        queue.resolve("a.m4a", from: pc, .blocked("Server refused (401)."), at: start.addingTimeInterval(123))

        #expect(queue.pending[0] == released)
    }

    @Test func aDeadFlightsLateConfirmationStillCounts() {
        var queue = stuckQueue()
        _ = queue.releaseStaleFlights(at: start.addingTimeInterval(121))

        queue.resolve("a.m4a", from: pc, .confirmed, at: start.addingTimeInterval(122))

        // A computer has it, whenever it got round to saying so. Only a
        // confirmation may speak for a flight already given up on.
        #expect(queue.pending.isEmpty)
    }
}
