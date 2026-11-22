from dataclasses import dataclass
import json
import sqlite3

from warehouse.dispatch.tickets import DeliveryTicket
from warehouse.storage import Database


@dataclass(frozen=True)
class TransferParameters:
    batch_id: str
    row_ids: tuple[str, ...]
    source: str
    destination: str


@dataclass(frozen=True)
class TransferOrder:
    order_id: str
    parameters: TransferParameters
    old_ticket_ids: tuple[int, ...]
    state: str


class TransferProgressStore:
    def __init__(self, database: Database):
        self.database = database

    def initialize_schema(self) -> None:
        with self.database.write() as connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS transfer_orders (
                    order_id TEXT PRIMARY KEY NOT NULL,
                    batch_id TEXT NOT NULL REFERENCES manifests(batch_id),
                    row_ids TEXT NOT NULL,
                    source TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    old_ticket_ids TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('accepted', 'pending', 'completed'))
                )
            ''')

    def get_order(self, connection: sqlite3.Connection, order_id: str) -> TransferOrder | None:
        record = connection.execute('SELECT * FROM transfer_orders WHERE order_id = ?',
                                    (order_id,)).fetchone()
        if record is None:
            return None
        parameters = TransferParameters(record['batch_id'], tuple(json.loads(record['row_ids'])),
                                        record['source'], record['destination'])
        return TransferOrder(order_id, parameters, tuple(json.loads(record['old_ticket_ids'])),
                             record['state'])

    def start_order(self, connection: sqlite3.Connection, order_id: str,
                    parameters: TransferParameters, tickets: tuple[DeliveryTicket, ...]
                    ) -> TransferOrder:
        ticket_ids = tuple(ticket.ticket_id for ticket in tickets)
        connection.execute('INSERT INTO transfer_orders VALUES (?, ?, ?, ?, ?, ?, ?)', (
            order_id, parameters.batch_id, json.dumps(parameters.row_ids), parameters.source,
            parameters.destination, json.dumps(ticket_ids), 'accepted',
        ))
        return TransferOrder(order_id, parameters, ticket_ids, 'accepted')

    def mark_pending(self, connection: sqlite3.Connection, order_id: str) -> None:
        self._update_state(connection, order_id, 'pending')

    def mark_completed(self, connection: sqlite3.Connection, order_id: str) -> None:
        self._update_state(connection, order_id, 'completed')

    def _update_state(self, connection: sqlite3.Connection, order_id: str, state: str) -> None:
        updated = connection.execute('''
            UPDATE transfer_orders SET state = ?
            WHERE order_id = ? AND state IN ('accepted', 'pending')
        ''', (state, order_id))
        if updated.rowcount != 1:
            raise RuntimeError(f'order {order_id!r} cannot transition to {state}')
