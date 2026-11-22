from dataclasses import dataclass
import sqlite3

from warehouse.source.rows import RowIdentity


WAREHOUSES = ('east', 'west')


def require_warehouse(warehouse: str) -> None:
    if warehouse not in WAREHOUSES:
        raise ValueError(f'unknown warehouse {warehouse!r}')


@dataclass(frozen=True)
class DeliveryTicket:
    ticket_id: int
    identity: RowIdentity
    warehouse: str
    generation: int


class TicketStore:
    def initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY,
                batch_id TEXT NOT NULL,
                row_id TEXT NOT NULL,
                warehouse TEXT NOT NULL CHECK (warehouse IN ('east', 'west')),
                generation INTEGER NOT NULL CHECK (generation > 0),
                UNIQUE (batch_id, row_id, generation),
                FOREIGN KEY (batch_id, row_id) REFERENCES manifest_rows(batch_id, row_id)
            )
        ''')

    def issue(self, connection: sqlite3.Connection, identity: RowIdentity,
              warehouse: str, generation: int) -> DeliveryTicket:
        cursor = connection.execute('''
            INSERT INTO tickets (batch_id, row_id, warehouse, generation)
            VALUES (?, ?, ?, ?)
        ''', (identity.batch_id, identity.row_id, warehouse, generation))
        return DeliveryTicket(cursor.lastrowid, identity, warehouse, generation)

    def get(self, connection: sqlite3.Connection, ticket_id: int) -> DeliveryTicket:
        record = connection.execute('''
            SELECT batch_id, row_id, warehouse, generation FROM tickets WHERE ticket_id = ?
        ''', (ticket_id,)).fetchone()
        if record is None:
            raise LookupError(f'unknown delivery ticket {ticket_id!r}')
        return DeliveryTicket(ticket_id, RowIdentity(record['batch_id'], record['row_id']),
                              record['warehouse'], record['generation'])
