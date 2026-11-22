import json

from tests.support import InterruptedOperation, LostReply, WarehouseCase, lose_reply, row_ids
from warehouse.dispatch.assignment import AssignmentConflict
from warehouse.posting.admission import DeliveryRejected
from warehouse.project import WarehouseProject
from warehouse.transfer.orders import TransferConflict


class TransferTests(WarehouseCase):
    def route_pair(self):
        self.seed()
        return self.project.dispatch('route', 'day-1', ['A', 'B'], 'east')

    def lose_first_reply(self, ticket):
        with self.assertRaises(LostReply) as captured:
            self.project.post('east', ticket, after_commit=lose_reply)
        project = self.reopen()
        receipt = project.queries['east'].get_receipt(ticket.ticket_id)
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.receipt_id, str(captured.exception))
        self.assertEqual(project.pending('east', 'day-1')[0], ticket)
        return receipt

    def test_remaining_rows(self):
        first, second = self.route_pair()
        receipt = self.project.post('east', first)
        result = self.project.transfer('relief', 'day-1', ['B'], 'east', 'west')
        self.assertEqual((result.state, result.retained, row_ids(result.moved)),
                         ('completed', (), ('B',)))
        new_ticket, = result.moved
        self.assertNotEqual(new_ticket.ticket_id, second.ticket_id)
        west = self.project.post('west', new_ticket)
        report = self.project.audit('day-1')
        self.assertEqual([(row.identity.row_id, row.warehouse, row.receipt_id) for row in report.entries],
                         [('A', 'east', receipt.receipt_id), ('B', 'west', west.receipt_id)])
        self.assert_totals(report, east=(1, 7), west=(1, 11), combined=(2, 18))

    def test_queue_after_transfer(self):
        first, second = self.route_pair()
        self.assertEqual(self.project.pending('east', 'day-1'), (first, second))
        original = self.project.post('east', first)
        result = self.project.transfer('relief', 'day-1', ['B', 'A'], 'east', 'west')
        self.assertEqual(result.retained, (original,))
        self.assertEqual(self.project.pending('east', 'day-1'), ())
        self.assertEqual(self.project.pending('west', 'day-1'), result.moved)
        new_ticket, = self.project.pending('west', 'day-1')
        self.assertFalse(self.project.assignments.status.confirm_receipt(
            type(original)('delayed', second.identity, 'east', second.ticket_id)
        ))
        self.assertEqual(self.project.pending('west', 'day-1'), (new_ticket,))
        self.project.post('west', new_ticket)
        self.assertEqual(self.project.pending('west', 'day-1'), ())
        self.assertEqual(row_ids(self.project.queries['east'].list_postings('day-1')), ('A',))
        self.assertEqual(row_ids(self.project.queries['west'].list_postings('day-1')), ('B',))

    def test_invalid_scope(self):
        self.seed(observations=(('A', 7), ('B', 11), ('C', 0)))
        east = self.project.dispatch('east-route', 'day-1', ['A', 'B'], 'east')
        west = self.project.dispatch('west-route', 'day-1', ['C'], 'west')
        with self.assertRaises(AssignmentConflict):
            self.project.transfer('relief', 'day-1', ['A', 'C'], 'east', 'west')
        with self.assertRaisesRegex(ValueError, 'unknown rows'):
            self.project.transfer('relief', 'day-1', ['A', 'missing'], 'east', 'west')
        self.assertEqual(self.project.pending('east', 'day-1'), east)
        self.assertEqual(self.project.pending('west', 'day-1'), west)
        result = self.project.transfer('relief', 'day-1', ['A'], 'east', 'west')
        self.assertEqual(row_ids(result.moved), ('A',))
        self.assertEqual(self.project.pending('east', 'day-1'), (east[1],))

    def test_lost_reply_classification(self):
        first, second = self.route_pair()
        original = self.lose_first_reply(first)
        self.assertEqual(self.project.pending('east', 'day-1'), (first, second))
        result = self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
        self.assertEqual(result.retained, (original,))
        self.assertEqual(row_ids(result.moved), ('B',))
        self.assertEqual(self.project.post('east', first), original)

    def test_lost_reply_and_late_post(self):
        first, second = self.route_pair()
        original = self.lose_first_reply(first)
        results = []
        west_receipts = {}

        def change_shift(admission):
            self.assertEqual(admission.ticket, second)
            replacement = WarehouseProject(self.root)
            result = replacement.transfer('relief', 'day-1', ['B', 'A'], 'east', 'west')
            results.append(result)
            for ticket in replacement.pending('west', 'day-1'):
                west_receipts[ticket.identity.row_id] = replacement.post('west', ticket).receipt_id

        refused = False
        try:
            self.project.post('east', second, after_admission=change_shift)
        except DeliveryRejected:
            refused = True
        result, = results
        project = self.reopen()
        east_rows = project.queries['east'].list_postings('day-1')
        west_rows = project.queries['west'].list_postings('day-1')
        actual = {
            'state': result.state,
            'retained': list(row_ids(result.retained)),
            'moved': list(row_ids(result.moved)),
            'old_post_refused': refused,
            'east': [[row.identity.row_id, row.liters] for row in east_rows],
            'west': [[row.identity.row_id, row.liters] for row in west_rows],
        }
        expected = {'state': 'completed', 'retained': ['A'], 'moved': ['B'],
                    'old_post_refused': True, 'east': [['A', 7]], 'west': [['B', 11]]}
        self.assertEqual(actual, expected, 'V6_HANDOFF_ACCOUNTING')
        self.assertEqual(result.retained, (original,))
        self.assertEqual(project.transfer('relief', 'day-1', ['B', 'A'], 'east', 'west'), result)
        with self.assertRaises(DeliveryRejected):
            project.post('east', second)
        report = project.audit('day-1')
        downstream_actual = {
            'rows': [[row.identity.row_id, row.origin, row.warehouse, row.receipt_id]
                     for row in report.entries],
            'count': report.totals.count,
            'liters': report.totals.liters,
        }
        downstream_expected = {
            'rows': [['A', 'day-1/field-sheet/A', 'east', original.receipt_id],
                     ['B', 'day-1/field-sheet/B', 'west', west_receipts['B']]],
            'count': 2,
            'liters': 18,
        }
        self.assertEqual(downstream_actual, downstream_expected, 'V6_HANDOFF_ACCOUNTING')
        self.assertEqual(report.unposted, ())
        self.assert_totals(report, east=(1, 7), west=(1, 11), combined=(2, 18))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v6',
            'input': {'A': 7, 'B': 11, 'lost_reply': 'A', 'paused': 'B', 'selection': ['B', 'A']},
            'expected': expected, 'actual': actual,
            'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
            'code_paths': ['warehouse/posting/ledger.py', 'warehouse/transfer/settlement.py',
                           'warehouse/transfer/orders.py', 'warehouse/audit/report.py'],
            'oracle': '手算 7 + 11，并把联合账的两个账号与各自仓内原回执独立对照',
        }, ensure_ascii=False, sort_keys=True))

    def test_stop_wins(self):
        first, second = self.route_pair()
        original = self.project.post('east', first)

        def transfer_before_write(admission):
            replacement = WarehouseProject(self.root)
            result = replacement.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
            self.assertEqual(result.retained, (original,))
            new_ticket, = result.moved
            self.assertEqual(new_ticket.identity, admission.ticket.identity)
            replacement.post('west', new_ticket)

        with self.assertRaises(DeliveryRejected):
            self.project.post('east', second, after_admission=transfer_before_write)
        self.assertIsNone(self.project.queries['east'].get_receipt(second.ticket_id))
        self.assertEqual(row_ids(self.project.queries['east'].list_postings('day-1')), ('A',))
        self.assertEqual(row_ids(self.project.queries['west'].list_postings('day-1')), ('B',))

    def test_post_wins(self):
        first, second = self.route_pair()
        original = self.lose_first_reply(first)
        results = []

        def transfer_after_write(receipt):
            replacement = WarehouseProject(self.root)
            result = replacement.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
            self.assertEqual(result.retained, (original, receipt))
            results.append(result)

        receipt = self.project.post('east', second, after_commit=transfer_after_write)
        result, = results
        self.assertEqual(result.moved, ())
        project = self.reopen()
        self.assertEqual(project.post('east', second), receipt)
        self.assertEqual(project.pending('west', 'day-1'), ())
        self.assert_totals(project.audit('day-1'), east=(2, 18), west=(0, 0), combined=(2, 18))

    def test_unknown_old_outcome(self):
        first, second = self.route_pair()
        original = self.project.post('east', first)
        self.seed('day-2', observations=(('D', 13),))
        other, = self.project.dispatch('other-route', 'day-2', ['D'], 'west')
        east_path = self.project.ledgers['east'].database.path
        offline_path = east_path.with_name('east-offline.sqlite3')
        east_path.rename(offline_path)
        try:
            pending = self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
            self.assertEqual((pending.state, pending.retained, pending.moved), ('pending', (), ()))
            project = self.reopen()
            self.assertEqual(project.pending('west', 'day-1'), ())
            self.assertEqual(project.pending('east', 'day-1'), ())
            self.assertEqual(project.assignments.status.get_current(second.identity).ticket, second)
            self.assertEqual(project.pending('west', 'day-2'), (other,))
            project.post('west', other)
            self.assertEqual(row_ids(project.queries['west'].list_postings('day-2')), ('D',))
            with self.assertRaises(TransferConflict):
                project.transfer('relief', 'day-1', ['B'], 'east', 'west')
        finally:
            offline_path.rename(east_path)
        resumed = self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
        self.assertEqual(resumed.retained, (original,))
        self.assertEqual(row_ids(resumed.moved), ('B',))
        self.project.post('west', resumed.moved[0])
        self.assert_totals(self.project.audit('day-1'), east=(1, 7), west=(1, 11), combined=(2, 18))
        self.assert_totals(self.project.audit('day-2'), east=(0, 0), west=(1, 13), combined=(1, 13))

    def test_batch_isolation(self):
        self.seed(observations=(('A', 7), ('B', 11), ('C', 0)))
        first, second, third = self.project.dispatch('route', 'day-1', ['A', 'B', 'C'], 'east')
        self.seed('day-2', observations=(('D', 5),))
        other, = self.project.dispatch('other', 'day-2', ['D'], 'east')
        # Hold a real SQLite writer to make old-ticket settlement temporarily unavailable.
        with self.project.ledgers['east'].database.write():
            pending = self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
            self.assertEqual(pending.state, 'pending')
            self.assertEqual(self.project.pending('east', 'day-1'), (third,))
            self.assertEqual(self.project.pending('east', 'day-2'), (other,))
            with self.assertRaises(AssignmentConflict):
                self.project.transfer('overlap', 'day-1', ['B', 'C'], 'east', 'west')
        project = self.reopen()
        self.assertEqual(project.pending('east', 'day-1'), (third,))
        receipt = project.post('east', project.pending('east', 'day-2')[0])
        self.assertEqual(receipt.identity, other.identity)
        result = project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
        self.assertEqual(tuple(ticket.identity for ticket in result.moved), (first.identity, second.identity))
        self.assertEqual(project.pending('east', 'day-1'), (third,))
        self.assertEqual(project.pending('east', 'day-2'), ())

    def test_retry_parameters(self):
        first, second = self.route_pair()
        self.project.post('east', first)
        parameters = ('relief', 'day-1', ['A', 'B'], 'east', 'west')
        result = self.project.transfer(*parameters)
        self.project.post('west', result.moved[0])
        before = self.project.audit('day-1')
        project = self.reopen()
        self.assertEqual(project.transfer(*parameters), result)
        with self.assertRaises(TransferConflict):
            project.transfer('relief', 'day-1', ['B'], 'east', 'west')
        with self.assertRaises(TransferConflict):
            project.transfer('relief', 'day-1', ['A', 'B'], 'west', 'east')
        self.assertEqual(project.transfer(*parameters), result)
        self.assertEqual(project.audit('day-1'), before)
        with self.assertRaises(DeliveryRejected):
            project.post('east', second)

    def test_publish_recovery(self):
        first, second = self.route_pair()
        original = self.lose_first_reply(first)
        reached = []

        def interrupt(result):
            reached.append(result.state)
            raise InterruptedOperation('coordination commit interrupted')

        with self.assertRaises(InterruptedOperation):
            self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west',
                                  before_publish_commit=interrupt)
        self.assertEqual(reached, ['completed'])
        project = self.reopen()
        self.assertEqual(project.pending('west', 'day-1'), ())
        self.assertEqual(project.assignments.status.get_current(second.identity).ticket, second)
        self.assertEqual(project.assignments.status.get_current(second.identity).reserved_order, 'relief')
        with project.coordination.read() as connection:
            self.assertNotEqual(project.transfers.progress.get_order(connection, 'relief').state,
                                'completed')
            with self.assertRaises(LookupError):
                project.transfers.results.load_result(connection, 'relief')
        with self.assertRaisesRegex(DeliveryRejected, 'stopped before posting'):
            project.post('east', second)
        result = project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
        self.assertEqual(result.retained, (original,))
        self.assertEqual(row_ids(result.moved), ('B',))
        self.assertEqual(project.pending('west', 'day-1'), result.moved)
        west = project.post('west', result.moved[0])
        reopened = self.reopen()
        self.assertEqual(reopened.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west'), result)
        self.assertEqual(reopened.post('west', result.moved[0]), west)
        self.assert_totals(reopened.audit('day-1'), east=(1, 7), west=(1, 11), combined=(2, 18))
