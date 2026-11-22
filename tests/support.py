from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warehouse.project import WarehouseProject
from warehouse.source.intake import prepare_draft


class InterruptedOperation(Exception):
    pass


class LostReply(Exception):
    pass


def lose_reply(receipt):
    raise LostReply(receipt.receipt_id)


def row_ids(items):
    return tuple(item.identity.row_id for item in items)


class WarehouseCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='station-day-tests-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.project = WarehouseProject(self.root)
        self.project.initialize()

    def draft(self, batch='day-1', observations=(('A', 7), ('B', 11))):
        return prepare_draft(batch, '青汀一站', '2026-05-12', (
            {'row_id': name, 'origin': f'{batch}/field-sheet/{name}', 'liters': liters}
            for name, liters in observations
        ))

    def seed(self, batch='day-1', observations=(('A', 7), ('B', 11))):
        return self.project.seal(self.draft(batch, observations))

    def reopen(self):
        self.project = WarehouseProject(self.root)
        return self.project

    def assert_totals(self, report, *, east, west, combined):
        self.assertEqual([(item.warehouse, item.count, item.liters)
                          for item in report.totals.per_warehouse],
                         [('east', *east), ('west', *west)])
        self.assertEqual((report.totals.count, report.totals.liters), combined)
