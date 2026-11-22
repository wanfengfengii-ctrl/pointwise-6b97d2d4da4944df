from collections.abc import Iterable
from dataclasses import dataclass

from warehouse.audit.reconciliation import AuditRow


@dataclass(frozen=True)
class WarehouseTotal:
    warehouse: str
    count: int
    liters: int


@dataclass(frozen=True)
class BatchTotals:
    per_warehouse: tuple[WarehouseTotal, ...]
    count: int
    liters: int


def sum_liters(entries: Iterable[AuditRow], warehouses: Iterable[str]) -> BatchTotals:
    counts = dict.fromkeys(warehouses, 0)
    liters = dict.fromkeys(counts, 0)
    for entry in entries:
        if entry.warehouse not in counts:
            raise ValueError(f'unexpected posting warehouse {entry.warehouse!r}')
        counts[entry.warehouse] += 1
        liters[entry.warehouse] += entry.liters
    totals = tuple(WarehouseTotal(warehouse, counts[warehouse], liters[warehouse])
                   for warehouse in counts)
    return BatchTotals(totals, sum(counts.values()), sum(liters.values()))
