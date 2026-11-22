from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass
class ManifestDraft:
    batch_id: str
    station: str
    day: str
    rows: list[dict[str, object]]


def prepare_draft(batch_id: str, station: str, day: str,
                  rows: Iterable[Mapping[str, object]]) -> ManifestDraft:
    snapshots = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError('each source row must be a mapping')
        snapshots.append(dict(row))
    return ManifestDraft(batch_id, station, day, snapshots)
