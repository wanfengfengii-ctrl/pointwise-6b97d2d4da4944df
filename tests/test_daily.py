from dataclasses import replace

from tests.support import InterruptedOperation, WarehouseCase, row_ids
from warehouse.dispatch.assignment import AssignmentConflict
from warehouse.posting.admission import DeliveryRejected
from warehouse.source.manifest import UnknownManifest


class DailyTests(WarehouseCase):
    def test_equal_values_distinct_rows(self):
        manifest = self.seed(observations=(('A', 7), ('B', 7)))
        self.assertEqual(row_ids(manifest.rows), ('A', 'B'))
        self.assertEqual(tuple(row.origin for row in manifest.rows),
                         ('day-1/field-sheet/A', 'day-1/field-sheet/B'))
        tickets = self.project.dispatch('route', 'day-1', ['A', 'B'], 'east')
        first = self.project.post('east', tickets[0])
        self.assertEqual(self.project.pending('east', 'day-1'), (tickets[1],))
        second = self.project.post('east', tickets[1])
        self.assertNotEqual(first.receipt_id, second.receipt_id)
        report = self.project.audit('day-1')
        self.assertEqual([(row.identity.row_id, row.origin, row.liters, row.receipt_id)
                          for row in report.entries],
                         [('A', 'day-1/field-sheet/A', 7, first.receipt_id),
                          ('B', 'day-1/field-sheet/B', 7, second.receipt_id)])
        self.assertEqual(report.unposted, ())
        self.assert_totals(report, east=(2, 14), west=(0, 0), combined=(2, 14))

    def test_draft_isolation(self):
        draft = self.draft()
        sealed = self.project.seal(draft)
        draft.rows.reverse()
        draft.rows[0]['liters'] = 900
        draft.rows[1]['origin'] = 'edited'
        project = self.reopen()
        self.assertEqual(project.manifests.get_manifest('day-1'), sealed)
        with self.assertRaisesRegex(ValueError, 'already sealed'):
            project.seal(draft)
        self.assertEqual(project.manifests.get_manifest('day-1'), sealed)
        self.assertEqual([(row.identity.row_id, row.origin, row.liters) for row in sealed.rows],
                         [('A', 'day-1/field-sheet/A', 7), ('B', 'day-1/field-sheet/B', 11)])

    def test_duplicate_source_row(self):
        with self.assertRaisesRegex(ValueError, 'duplicate source row'):
            self.project.seal(self.draft(observations=(('A', 7), ('B', 11), ('A', 3))))
        project = self.reopen()
        with self.assertRaises(UnknownManifest):
            project.manifests.get_manifest('day-1')
        with self.assertRaises(UnknownManifest):
            project.dispatch('route', 'day-1', ['A'], 'east')
        self.assertEqual(row_ids(self.seed().rows), ('A', 'B'))

    def test_invalid_values(self):
        for field, value in [('origin', ''), ('origin', None), ('liters', None),
                             ('liters', -1), ('liters', 7.5), ('liters', True)]:
            with self.subTest(field=field, value=value):
                draft = self.draft()
                draft.rows[1][field] = value
                with self.assertRaises(ValueError):
                    self.project.seal(draft)
                with self.assertRaises(UnknownManifest):
                    self.project.manifests.get_manifest('day-1')
        invalid_day = self.draft()
        invalid_day.day = '2026-02-30'
        with self.assertRaises(ValueError):
            self.project.seal(invalid_day)
        self.assertEqual(row_ids(self.seed().rows), ('A', 'B'))

    def test_wrong_receiver(self):
        self.seed()
        ticket, = self.project.dispatch('route', 'day-1', ['A'], 'east')
        with self.assertRaises(DeliveryRejected):
            self.project.post('west', ticket)
        with self.assertRaises(DeliveryRejected):
            self.project.post('west', replace(ticket, warehouse='west'))
        self.assertEqual(self.project.queries['west'].list_postings('day-1'), ())
        self.assertIsNone(self.project.queries['west'].get_receipt(ticket.ticket_id))
        receipt = self.project.post('east', ticket)
        self.assertEqual(self.project.queries['east'].get_receipt(ticket.ticket_id), receipt)
        self.assertEqual(receipt.warehouse, 'east')

    def test_dispatch_atomic(self):
        self.seed(observations=(('A', 7), ('B', 11), ('C', 0)))
        with self.assertRaisesRegex(ValueError, 'unknown rows'):
            self.project.dispatch('east-route', 'day-1', ['A', 'missing'], 'east')
        self.assertEqual(self.project.pending('east', 'day-1'), ())
        original = self.project.dispatch('east-route', 'day-1', ['C', 'A'], 'east')
        self.assertEqual(row_ids(original), ('A', 'C'))
        with self.assertRaises(AssignmentConflict):
            self.project.dispatch('west-route', 'day-1', ['B', 'A'], 'west')
        self.assertEqual(self.project.pending('west', 'day-1'), ())
        project = self.reopen()
        self.assertEqual(project.dispatch('east-route', 'day-1', ['C', 'A'], 'east'), original)
        with self.assertRaisesRegex(AssignmentConflict, 'different parameters'):
            project.dispatch('east-route', 'day-1', ['A', 'C'], 'east')
        self.assertEqual(row_ids(project.dispatch('west-route', 'day-1', ['B'], 'west')), ('B',))

    def test_failed_post_retry(self):
        self.seed()
        ticket, = self.project.dispatch('route', 'day-1', ['A'], 'east')
        attempted = []

        def fail_before_commit(receipt):
            attempted.append(receipt)
            raise InterruptedOperation('posting commit interrupted')

        with self.assertRaises(InterruptedOperation):
            self.project.post('east', ticket, before_commit=fail_before_commit)
        self.assertEqual(len(attempted), 1)
        project = self.reopen()
        self.assertEqual(project.queries['east'].list_postings('day-1'), ())
        self.assertIsNone(project.queries['east'].get_receipt(ticket.ticket_id))
        self.assertEqual(project.pending('east', 'day-1'), (ticket,))
        receipt = project.post('east', ticket)
        self.assertEqual(project.queries['east'].get_receipt(ticket.ticket_id), receipt)
        self.assertEqual(row_ids(project.queries['east'].list_postings('day-1')), ('A',))
        self.assertEqual(project.pending('east', 'day-1'), ())

    def test_committed_replay(self):
        self.seed()
        ticket, = self.project.dispatch('route', 'day-1', ['B'], 'east')
        original = self.project.post('east', ticket)
        project = self.reopen()
        self.assertEqual(project.post('east', ticket), original)
        self.assertEqual(project.queries['east'].get_receipt(ticket.ticket_id), original)
        self.assertEqual(row_ids(project.queries['east'].list_postings('day-1')), ('B',))
        self.assert_totals(project.audit('day-1'), east=(1, 11), west=(0, 0), combined=(1, 11))
