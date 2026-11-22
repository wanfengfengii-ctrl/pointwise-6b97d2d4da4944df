from collections.abc import Iterable
import sqlite3

from warehouse.source.rows import (
    RowIdentity, SealedManifest, SourceRow, decode_liters, encode_liters,
)
from warehouse.source.validation import require_text
from warehouse.storage import Database


class UnknownManifest(LookupError):
    pass


def selection_ids(row_ids: Iterable[str]) -> tuple[str, ...]:
    if isinstance(row_ids, (str, bytes)):
        raise ValueError('row_ids requires a sequence of row names')
    names = tuple(require_text(row_id, 'row_id') for row_id in row_ids)
    if not names or len(set(names)) != len(names):
        raise ValueError('row selection must be nonempty and contain unique names')
    return names


class ManifestStore:
    def __init__(self, database: Database):
        self.database = database

    def initialize_schema(self) -> None:
        with self.database.write(create=True) as connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS manifests (
                    batch_id TEXT PRIMARY KEY NOT NULL,
                    station TEXT NOT NULL,
                    day TEXT NOT NULL
                )
            ''')
            connection.execute('''
                CREATE TABLE IF NOT EXISTS manifest_rows (
                    batch_id TEXT NOT NULL REFERENCES manifests(batch_id),
                    row_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    origin TEXT NOT NULL,
                    liters BLOB NOT NULL,
                    PRIMARY KEY (batch_id, row_id),
                    UNIQUE (batch_id, position)
                )
            ''')

    def publish(self, manifest: SealedManifest) -> SealedManifest:
        with self.database.write() as connection:
            existing = connection.execute(
                'SELECT 1 FROM manifests WHERE batch_id = ?', (manifest.batch_id,)
            ).fetchone()
            if existing is not None:
                raise ValueError(f'manifest {manifest.batch_id!r} already sealed')
            connection.execute(
                'INSERT INTO manifests VALUES (?, ?, ?)',
                (manifest.batch_id, manifest.station, manifest.day),
            )
            connection.executemany(
                'INSERT INTO manifest_rows VALUES (?, ?, ?, ?, ?)',
                ((manifest.batch_id, row.identity.row_id, position,
                  row.origin, encode_liters(row.liters))
                 for position, row in enumerate(manifest.rows)),
            )
        return manifest

    def get_manifest(self, batch_id: str, *,
                     connection: sqlite3.Connection | None = None) -> SealedManifest:
        if connection is None:
            with self.database.read() as reader:
                return self.get_manifest(batch_id, connection=reader)
        metadata = connection.execute(
            'SELECT station, day FROM manifests WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        if metadata is None:
            raise UnknownManifest(f'unknown manifest {batch_id!r}')
        records = connection.execute('''
            SELECT row_id, origin, liters FROM manifest_rows
            WHERE batch_id = ? ORDER BY position
        ''', (batch_id,))
        rows = tuple(
            SourceRow(RowIdentity(batch_id, record['row_id']), record['origin'],
                      decode_liters(record['liters']))
            for record in records
        )
        return SealedManifest(batch_id, metadata['station'], metadata['day'], rows)

    def select_rows(self, batch_id: str, row_ids: Iterable[str], *,
                    connection: sqlite3.Connection | None = None) -> tuple[SourceRow, ...]:
        names = set(selection_ids(row_ids))
        manifest = self.get_manifest(batch_id, connection=connection)
        selected = tuple(row for row in manifest.rows if row.identity.row_id in names)
        unknown = names.difference(row.identity.row_id for row in selected)
        if unknown:
            raise ValueError(f'unknown rows in {batch_id!r}: {sorted(unknown)!r}')
        return selected
