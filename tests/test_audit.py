from tests.support import WarehouseCase, row_ids
from warehouse.audit.coverage import DuplicatePosting
from warehouse.source.manifest import UnknownManifest


class AuditTests(WarehouseCase):
    def test_pending_and_totals(self):
        self.seed(observations=(('A', 7), ('B', 11), ('C', 0)))
        first, second, third = self.project.dispatch('route', 'day-1', ['A', 'B', 'C'], 'east')
        east = self.project.post('east', first)
        result = self.project.transfer('relief', 'day-1', ['B'], 'east', 'west')
        west = self.project.post('west', result.moved[0])
        self.assertNotEqual(second.ticket_id, result.moved[0].ticket_id)
        report = self.project.audit('day-1')
        self.assertEqual([(entry.identity.row_id, entry.warehouse, entry.receipt_id)
                          for entry in report.entries],
                         [('A', 'east', east.receipt_id), ('B', 'west', west.receipt_id)])
        self.assertEqual([(row.identity.row_id, row.origin) for row in report.unposted],
                         [('C', 'day-1/field-sheet/C')])
        self.assert_totals(report, east=(1, 7), west=(1, 11), combined=(2, 18))
        self.assertEqual(self.project.pending('east', 'day-1'), (third,))
        zero = self.project.post('east', third)
        report = self.project.audit('day-1')
        self.assertEqual(row_ids(report.entries), ('A', 'B', 'C'))
        self.assertEqual(report.entries[2].receipt_id, zero.receipt_id)
        self.assertEqual(report.unposted, ())
        self.assert_totals(report, east=(2, 7), west=(1, 11), combined=(3, 18))

    def test_nonprefix_pending(self):
        self.seed(observations=(('C', 0), ('A', 7), ('B', 11)))
        third, first = self.project.dispatch('east-route', 'day-1', ['A', 'C'], 'east')
        second, = self.project.dispatch('west-route', 'day-1', ['B'], 'west')
        self.project.post('west', second)
        self.project.post('east', first)
        report = self.project.audit('day-1')
        self.assertEqual(row_ids(report.entries), ('A', 'B'))
        self.assertEqual([(row.identity.row_id, row.origin) for row in report.unposted],
                         [('C', 'day-1/field-sheet/C')])
        self.project.post('east', third)
        report = self.project.audit('day-1')
        self.assertEqual(row_ids(report.entries), ('C', 'A', 'B'))
        self.assertEqual(report.unposted, ())
        self.assert_totals(report, east=(2, 7), west=(1, 11), combined=(3, 18))

    def test_exact_liters(self):
        large = 1_208_925_819_614_629_174_706_187
        self.seed(observations=(('zero', 0), ('large', large), ('small', 7)))
        zero, east = self.project.dispatch('east-route', 'day-1', ['zero', 'large'], 'east')
        west, = self.project.dispatch('west-route', 'day-1', ['small'], 'west')
        self.project.post('west', west)
        self.project.post('east', east)
        self.project.post('east', zero)
        report = self.reopen().audit('day-1')
        self.assertEqual([row.liters for row in report.entries], [0, large, 7])
        self.assert_totals(report, east=(2, large), west=(1, 7),
                           combined=(3, 1_208_925_819_614_629_174_706_194))

    def test_duplicate_posting(self):
        self.seed()
        first, = self.project.dispatch('east-route', 'day-1', ['A'], 'east')
        second, = self.project.dispatch('west-route', 'day-1', ['B'], 'west')
        east = self.project.post('east', first)
        west = self.project.post('west', second)
        database = self.project.ledgers['west'].database
        with database.write() as connection:
            inserted = connection.execute('''
                INSERT INTO posted_rows (ticket_id, batch_id, row_id, origin, liters)
                VALUES (?, 'day-1', 'A', 'day-1/field-sheet/A', ?)
            ''', (first.ticket_id, bytes([7])))
            connection.execute('INSERT INTO receipts VALUES (?, ?, ?)',
                               (first.ticket_id, inserted.lastrowid, 'west-fixture-duplicate'))
        with self.assertRaisesRegex(DuplicatePosting, 'duplicate posting for day-1/A'):
            self.project.audit('day-1')
        with database.write() as connection:
            connection.execute('DELETE FROM receipts WHERE ticket_id = ?', (first.ticket_id,))
            connection.execute('DELETE FROM posted_rows WHERE ticket_id = ?', (first.ticket_id,))
        report = self.project.audit('day-1')
        self.assertEqual(tuple(row.receipt_id for row in report.entries),
                         (east.receipt_id, west.receipt_id))
        self.assert_totals(report, east=(1, 7), west=(1, 11), combined=(2, 18))

    def test_unknown_manifest(self):
        with self.assertRaisesRegex(UnknownManifest, 'unknown manifest'):
            self.project.audit('never-sealed')
