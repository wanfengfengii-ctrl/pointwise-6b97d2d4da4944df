from dataclasses import dataclass
import json
import sqlite3


@dataclass(frozen=True)
class DispatchRequest:
    batch_id: str
    row_ids: tuple[str, ...]
    warehouse: str


class DispatchRequestStore:
    def initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute('''
            CREATE TABLE IF NOT EXISTS dispatch_requests (
                request_id TEXT PRIMARY KEY NOT NULL,
                batch_id TEXT NOT NULL REFERENCES manifests(batch_id),
                row_ids TEXT NOT NULL,
                warehouse TEXT NOT NULL,
                ticket_ids TEXT NOT NULL
            )
        ''')

    def lookup_request(self, connection: sqlite3.Connection, request_id: str
                       ) -> tuple[DispatchRequest, tuple[int, ...]] | None:
        record = connection.execute('''
            SELECT batch_id, row_ids, warehouse, ticket_ids
            FROM dispatch_requests WHERE request_id = ?
        ''', (request_id,)).fetchone()
        if record is None:
            return None
        request = DispatchRequest(record['batch_id'], tuple(json.loads(record['row_ids'])),
                                  record['warehouse'])
        return request, tuple(json.loads(record['ticket_ids']))

    def save_request(self, connection: sqlite3.Connection, request_id: str,
                     request: DispatchRequest, ticket_ids: tuple[int, ...]) -> None:
        connection.execute('INSERT INTO dispatch_requests VALUES (?, ?, ?, ?, ?)', (
            request_id, request.batch_id, json.dumps(request.row_ids),
            request.warehouse, json.dumps(ticket_ids),
        ))
