import Foundation
import Testing
@testable import HighdeasKit

private let t0 = Date(timeIntervalSince1970: 1_780_000_000)
private let spoken = Date(timeIntervalSince1970: 1_779_999_000)

@Suite struct DeliveryReceiptsTests {
    @Test func aConfirmedRecordingKeepsShowing() {
        // The whole point: the row does not vanish the instant the file does.
        var receipts = DeliveryReceipts()
        receipts.confirm("a.m4a", recordedAt: spoken, at: t0)

        #expect(receipts.showing.map(\.fileName) == ["a.m4a"])
        #expect(receipts.showing[0].recordedAt == spoken)
    }

    @Test func aSecondMachineConfirmingDoesNotRestartTheClock() {
        // Every peer gets the same push, so the same recording is confirmed more
        // than once. A receipt that reset each time would outstay its welcome by
        // however long the slowest machine took to answer.
        var receipts = DeliveryReceipts()
        receipts.confirm("a.m4a", recordedAt: spoken, at: t0)
        receipts.confirm("a.m4a", recordedAt: spoken, at: t0.addingTimeInterval(3))

        #expect(receipts.showing.count == 1)
        #expect(receipts.showing[0].deliveredAt == t0)
    }

    @Test func aReceiptLeavesOnceItHasBeenRead() {
        var receipts = DeliveryReceipts()
        receipts.confirm("a.m4a", recordedAt: spoken, at: t0)

        receipts.prune(at: t0.addingTimeInterval(DeliveryReceipts.linger - 0.5))
        #expect(receipts.showing.count == 1)

        receipts.prune(at: t0.addingTimeInterval(DeliveryReceipts.linger))
        #expect(receipts.showing.isEmpty)
    }

    @Test func pruningKeepsTheYoungerReceipts() {
        var receipts = DeliveryReceipts()
        receipts.confirm("early.m4a", recordedAt: spoken, at: t0)
        receipts.confirm("late.m4a", recordedAt: spoken, at: t0.addingTimeInterval(5))

        receipts.prune(at: t0.addingTimeInterval(DeliveryReceipts.linger + 1))

        #expect(receipts.showing.map(\.fileName) == ["late.m4a"])
    }

    @Test func theNextExpiryIsTheOldestReceiptsAndNilWhenEmpty() {
        // The caller wakes exactly when a receipt stops being true, rather than
        // leaving it on screen until whatever happens next happens.
        var receipts = DeliveryReceipts()
        #expect(receipts.nextExpiry() == nil)

        receipts.confirm("late.m4a", recordedAt: spoken, at: t0.addingTimeInterval(5))
        receipts.confirm("early.m4a", recordedAt: spoken, at: t0)

        #expect(receipts.nextExpiry() == t0.addingTimeInterval(DeliveryReceipts.linger))
    }
}
