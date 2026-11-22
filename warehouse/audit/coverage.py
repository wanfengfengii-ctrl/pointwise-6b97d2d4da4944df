from collections.abc import Iterable, Mapping

from warehouse.posting.queries import PostedRow
from warehouse.source.rows import RowIdentity, SealedManifest, SourceRow


class DuplicatePosting(ValueError):
    pass


def index_postings(postings: Iterable[PostedRow]) -> dict[RowIdentity, PostedRow]:
    indexed = {}
    for posting in postings:
        previous = indexed.get(posting.identity)
        if previous is not None:
            raise DuplicatePosting(
                f'duplicate posting for {posting.identity.batch_id}/{posting.identity.row_id} '
                f'({previous.receipt_id}, {posting.receipt_id})'
            )
        indexed[posting.identity] = posting
    return indexed


def find_unposted_rows(manifest: SealedManifest,
                       indexed: Mapping[RowIdentity, PostedRow]) -> tuple[SourceRow, ...]:
    return tuple(row for row in manifest.rows if row.identity not in indexed)
