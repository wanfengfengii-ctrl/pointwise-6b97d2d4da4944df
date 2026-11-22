import json
from pathlib import Path
from tempfile import TemporaryDirectory

from warehouse.project import WarehouseProject
from warehouse.source.intake import prepare_draft


def report_values(report):
    return {
        'rows': [[row.identity.row_id, row.origin, row.warehouse, row.liters]
                 for row in report.entries],
        'receipts': {row.identity.row_id: row.receipt_id for row in report.entries},
        'unposted': [[row.identity.row_id, row.origin] for row in report.unposted],
        'per_warehouse': {total.warehouse: [total.count, total.liters]
                          for total in report.totals.per_warehouse},
        'total': [report.totals.count, report.totals.liters],
    }


def main():
    sample_path = Path(__file__).resolve().parent / 'examples' / 'station-day.json'
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='station-day-demo-') as directory:
        project = WarehouseProject(directory)
        project.initialize()
        manifest = project.seal(prepare_draft(**sample))
        batch_id = manifest.batch_id
        first, second, third = project.dispatch('morning', batch_id, ['A', 'B', 'C'], 'east')
        east = project.post('east', first)
        transfer = project.transfer('relief', batch_id, ['A', 'B'], 'east', 'west')
        if (transfer.state, transfer.retained) != ('completed', (east,)):
            raise AssertionError('the relief shift must preserve the east receipt')
        new_ticket, = project.pending('west', batch_id)
        if new_ticket.identity != second.identity or transfer.moved != (new_ticket,):
            raise AssertionError('the relief shift must receive the original row B')
        west = project.post('west', new_ticket)
        before = report_values(project.audit(batch_id))
        expected_before = {
            'rows': [['A', '北堤抄表单/01', 'east', 7], ['B', '南门抄表单/02', 'west', 11]],
            'receipts': {'A': east.receipt_id, 'B': west.receipt_id},
            'unposted': [['C', '巡测抄表单/03']],
            'per_warehouse': {'east': [1, 7], 'west': [1, 11]},
            'total': [2, 18],
        }
        zero_ticket, = project.pending('east', batch_id)
        if zero_ticket != third:
            raise AssertionError('the report must lead to the outstanding east ticket')
        zero = project.post('east', zero_ticket)
        reopened = WarehouseProject(directory)
        after = report_values(reopened.audit(batch_id))
        expected_after = {
            'rows': [*expected_before['rows'], ['C', '巡测抄表单/03', 'east', 0]],
            'receipts': {**expected_before['receipts'], 'C': zero.receipt_id},
            'unposted': [],
            'per_warehouse': {'east': [2, 7], 'west': [1, 11]},
            'total': [3, 18],
        }
        if before != expected_before or after != expected_after:
            raise AssertionError(f'unexpected station-day reconciliation: {before!r}, {after!r}')
        if reopened.transfer('relief', batch_id, ['A', 'B'], 'east', 'west') != transfer:
            raise AssertionError('the recorded relief order must replay after reopening')
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v9', 'input': sample,
            'expected': expected_before, 'actual': before,
            'downstream_expected': expected_after, 'downstream_actual': after,
            'code_paths': ['warehouse/audit/coverage.py', 'warehouse/audit/reconciliation.py',
                           'warehouse/audit/totals.py', 'warehouse/audit/report.py'],
            'oracle': '按样例手算 7 + 11 + 0 L，核回三笔原始出处及实入账号',
        }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
