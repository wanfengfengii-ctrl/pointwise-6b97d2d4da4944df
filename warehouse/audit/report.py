from collections.abc import Iterable
from dataclasses import dataclass

from warehouse.audit.reconciliation import AuditRow, reconcile_manifest
from warehouse.audit.totals import BatchTotals, sum_liters
from warehouse.posting.queries import WarehouseQueries
from warehouse.source.manifest import ManifestStore
from warehouse.source.rows import SourceRow


@dataclass(frozen=True)
class AuditReport:
    batch_id: str
    entries: tuple[AuditRow, ...]
    unposted: tuple[SourceRow, ...]
    totals: BatchTotals


def audit(manifests: ManifestStore, warehouses: Iterable[WarehouseQueries],
          batch_id: str) -> AuditReport:
    manifest = manifests.get_manifest(batch_id)
    readers = tuple(warehouses)
    postings = (posting for reader in readers for posting in reader.list_postings(batch_id))
    reconciled = reconcile_manifest(manifest, postings)
    totals = sum_liters(reconciled.entries, (reader.warehouse for reader in readers))
    return AuditReport(batch_id, reconciled.entries, reconciled.unposted, totals)
