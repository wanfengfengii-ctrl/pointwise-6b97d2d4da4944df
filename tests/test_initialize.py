import json
from pathlib import Path
import subprocess
import sys

from tests.support import WarehouseCase


class InitializeTests(WarehouseCase):
    def test_initialize_preserves_results(self):
        original_manifest = self.seed()
        first, second = self.project.dispatch('route', 'day-1', ['A', 'B'], 'east')
        original_receipt = self.project.post('east', first)
        original_result = self.project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
        west = self.project.post('west', original_result.moved[0])
        child_code = '''
import json
import sys
from warehouse.project import WarehouseProject

project = WarehouseProject(sys.argv[1])
project.initialize()
project.initialize()
manifest = project.manifests.get_manifest('day-1')
tickets = project.dispatch('route', 'day-1', ['A', 'B'], 'east')
result = project.transfer('relief', 'day-1', ['A', 'B'], 'east', 'west')
print(json.dumps({
    'source': [[row.identity.row_id, row.origin, row.liters] for row in manifest.rows],
    'tickets': [ticket.ticket_id for ticket in tickets],
    'retained': [receipt.receipt_id for receipt in result.retained],
    'moved': [ticket.ticket_id for ticket in result.moved],
    'east_receipt': project.post('east', tickets[0]).receipt_id,
    'west_receipt': project.post('west', result.moved[0]).receipt_id,
    'total': project.audit('day-1').totals.liters,
}))
'''
        child = subprocess.run([sys.executable, '-B', '-c', child_code, str(self.root)],
                               cwd=Path(__file__).resolve().parents[1],
                               check=True, text=True, capture_output=True, timeout=20)
        actual = json.loads(child.stdout)
        self.assertEqual(actual, {
            'source': [['A', 'day-1/field-sheet/A', 7], ['B', 'day-1/field-sheet/B', 11]],
            'tickets': [first.ticket_id, second.ticket_id],
            'retained': [original_receipt.receipt_id],
            'moved': [original_result.moved[0].ticket_id],
            'east_receipt': original_receipt.receipt_id,
            'west_receipt': west.receipt_id,
            'total': 18,
        })
        self.assertEqual(self.project.manifests.get_manifest('day-1'), original_manifest)
        report = self.project.audit('day-1')
        self.assertEqual(report.unposted, ())
        self.assert_totals(report, east=(1, 7), west=(1, 11), combined=(2, 18))
