from warehouse.source.intake import ManifestDraft
from warehouse.source.manifest import ManifestStore
from warehouse.source.rows import SealedManifest
from warehouse.source.validation import validate_rows, validate_station_day


def seal(store: ManifestStore, draft: ManifestDraft) -> SealedManifest:
    validate_station_day(draft.station, draft.day)
    rows = validate_rows(draft)
    return store.publish(SealedManifest(draft.batch_id, draft.station, draft.day, rows))
