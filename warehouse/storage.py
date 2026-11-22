from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


class Database:
    """Open a connection for one local transaction."""

    def __init__(self, path: Path):
        self.path = path.absolute()

    @contextmanager
    def _transaction(self, mode: str, begin: str) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f'{self.path.as_uri()}?mode={mode}', uri=True,
            isolation_level=None, timeout=0.5,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute(begin)
            with connection:
                yield connection
        finally:
            connection.close()

    def read(self):
        return self._transaction('ro', 'BEGIN')

    def write(self, *, create: bool = False):
        mode = 'rwc' if create else 'rw'
        return self._transaction(mode, 'BEGIN IMMEDIATE')
