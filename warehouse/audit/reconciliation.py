from collections.abc import Iterable
from dataclasses import dataclass

from warehouse.audit.coverage import find_unposted_rows, index_postings
from warehouse.posting.queries import PostedRow
from warehouse.source.rows import RowIdentity, SealedManifest, SourceRow


@dataclass(frozen=True)
class AuditRow:
    identity: RowIdentity
    origin: str
    liters: int
    warehouse: str
    receipt_id: str


@dataclass(frozen=True)
class ReconciledBatch:
    entries: tuple[AuditRow, ...]
    unposted: tuple[SourceRow, ...]


def reconcile_manifest(manifest: SealedManifest, postings: Iterable[PostedRow]) -> ReconciledBatch:
    indexed = index_postings(postings)
    source_keys = {row.identity for row in manifest.rows}
    unexpected = indexed.keys() - source_keys
    if unexpected:
        names = sorted((identity.batch_id, identity.row_id) for identity in unexpected)
        raise ValueError(f'postings outside the sealed manifest: {names!r}')
    entries = []
    for row in manifest.rows:
        posting = indexed.get(row.identity)
        if posting is None:
            continue
        if (posting.origin, posting.liters) != (row.origin, row.liters):
            raise ValueError(f'posting {posting.receipt_id!r} disagrees with the sealed row')
        entries.append(AuditRow(row.identity, row.origin, row.liters, posting.warehouse,
                                posting.receipt_id))
    return ReconciledBatch(tuple(entries), find_unposted_rows(manifest, indexed))
