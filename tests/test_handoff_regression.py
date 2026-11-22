"""Regressions for the inter-warehouse handoff settlement bugs.

Covers the two durable-outcome rules:
* a receipt already committed in the source warehouse keeps the row there even
  when the coordination confirmation reply was lost;
* a ticket stopped by a handoff rejects a late warehouse write.
"""
from tests.support import InterruptedOperation, LostReply, WarehouseCase, lose_reply, row_ids
from warehouse.posting.admission import DeliveryRejected
from warehouse.posting.disposition import PostingObservation
from warehouse.posting.receipts import Receipt
from warehouse.source.rows import RowIdentity
from warehouse.transfer.settlement import classify_transfer_rows
from warehouse.dispatch.tickets import DeliveryTicket


class HandoffRegressionTests(WarehouseCase):
    def route_pair(self):
        self.seed()
        return self.project.dispatch('route', 'day-1', ['A', 'B'], 'east')

    def test_durable_receipt_retained_without_confirmation(self):
        # A's 7 L are durably posted in east but the coordination reply is
        # lost, so the assignment is never confirmed there. B is only ticketed.
        first, second = self.route_pair()
        with self.assertRaises(LostReply):
            self.project.post('east', first, after_commit=lose_reply)
        status = self.project.assignments.status.get_current(first.identity)
        self.assertIsNone(status.confirmed_receipt)
        self.assertIsNotNone(self.project.queries['east'].get_receipt(first.ticket_id))

        result = self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
        self.assertEqual(result.state, 'completed')
        retained, = result.retained
        self.assertEqual((retained.identity.row_id, retained.warehouse, retained.receipt_id),
                         ('A', 'east', 'east-1'))
        self.assertEqual(row_ids(result.moved), ('B',))

        # The stopped old ticket can no longer be posted in east (it was
        # superseded by the west ticket).
        with self.assertRaisesRegex(DeliveryRejected,
                                    'stopped before posting|no longer assigned'):
            self.project.post('east', second)
        west = self.project.post('west', result.moved[0])
        report = self.project.audit('day-1')
        self.assertEqual(
            [(row.identity.row_id, row.origin, row.warehouse, row.receipt_id)
             for row in report.entries],
            [('A', 'day-1/field-sheet/A', 'east', 'east-1'),
             ('B', 'day-1/field-sheet/B', 'west', west.receipt_id)],
        )
        self.assertEqual(report.unposted, ())
        self.assert_totals(report, east=(1, 7), west=(1, 11), combined=(2, 18))

    def test_publish_rollback_leaves_no_new_ticket_and_blocks_old_post(self):
        first, second = self.route_pair()

        def interrupt(result):
            raise InterruptedOperation('coordination commit interrupted')

        with self.assertRaises(InterruptedOperation):
            self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west',
                                  before_publish_commit=interrupt)
        project = self.reopen()
        # No new west ticket and no completed result may survive the failure.
        self.assertEqual(project.pending('west', 'day-1'), ())
        self.assertEqual(project.assignments.status.get_current(second.identity).ticket, second)
        # The reserved (stopped) old ticket still refuses the late write.
        with self.assertRaisesRegex(DeliveryRejected, 'stopped before posting'):
            project.post('east', second)
        self.assertIsNone(project.queries['east'].get_receipt(second.ticket_id))

        # Reopening the same order resumes and settles with the same parameters.
        resumed = project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
        self.assertEqual(row_ids(resumed.moved), ('A', 'B'))
        self.assertEqual(project.pending('west', 'day-1'), resumed.moved)

    def test_classification_ignores_missing_coordination_confirmation(self):
        identity = RowIdentity('day-1', 'A')
        ticket = DeliveryTicket(1, identity, 'east', 1)
        receipt = Receipt('east-1', identity, 'east', 1)
        retained, movable = classify_transfer_rows(
            (ticket,), (PostingObservation(ticket, receipt),))
        self.assertEqual(retained, (receipt,))
        self.assertEqual(movable, ())

        retained, movable = classify_transfer_rows(
            (ticket,), (PostingObservation(ticket, None),))
        self.assertEqual(retained, ())
        self.assertEqual(movable, (ticket,))
