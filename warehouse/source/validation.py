from collections.abc import Mapping
from datetime import date

from warehouse.source.intake import ManifestDraft
from warehouse.source.rows import RowIdentity, SourceRow


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{field} must be nonblank text')
    return value


def validate_station_day(station: str, day: str) -> None:
    require_text(station, 'station')
    require_text(day, 'day')
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError('day must have YYYY-MM-DD format')


def validate_rows(draft: ManifestDraft) -> tuple[SourceRow, ...]:
    batch_id = require_text(draft.batch_id, 'batch_id')
    if not draft.rows:
        raise ValueError('manifest requires at least one source row')
    seen = set()
    rows = []
    for raw in draft.rows:
        if not isinstance(raw, Mapping):
            raise ValueError('each source row must be a mapping')
        row_id = require_text(raw.get('row_id'), 'row_id')
        if row_id in seen:
            raise ValueError(f'duplicate source row {row_id!r}')
        origin = require_text(raw.get('origin'), 'origin')
        liters = raw.get('liters')
        if type(liters) is not int or liters < 0:
            raise ValueError(f'row {row_id!r} requires nonnegative integer liters')
        rows.append(SourceRow(RowIdentity(batch_id, row_id), origin, liters))
        seen.add(row_id)
    return tuple(rows)
