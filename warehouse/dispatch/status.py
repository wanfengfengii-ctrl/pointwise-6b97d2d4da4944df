from dataclasses import dataclass
import sqlite3

from warehouse.dispatch.tickets import DeliveryTicket, TicketStore
from warehouse.posting.receipts import Receipt
from warehouse.source.rows import RowIdentity
from warehouse.storage import Database


@dataclass(frozen=True)
class AssignmentStatus:
    ticket: DeliveryTicket
    confirmed_receipt: str | None
    reserved_order: str | None


class DispatchStatusStore:
    def __init__(self, database: Database, tickets: TicketStore):
        self.database = database
        self.tickets = tickets

    def initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute('''
            CREATE TABLE IF NOT EXISTS assignments (
                batch_id TEXT NOT NULL,
                row_id TEXT NOT NULL,
                ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets(ticket_id),
                confirmed_receipt TEXT,
                reserved_order TEXT,
                PRIMARY KEY (batch_id, row_id),
                FOREIGN KEY (batch_id, row_id) REFERENCES manifest_rows(batch_id, row_id)
            )
        ''')

    def get_current(self, identity: RowIdentity, *,
                    connection: sqlite3.Connection | None = None) -> AssignmentStatus | None:
        if connection is None:
            with self.database.read() as reader:
                return self.get_current(identity, connection=reader)
        record = connection.execute('''
            SELECT ticket_id, confirmed_receipt, reserved_order FROM assignments
            WHERE batch_id = ? AND row_id = ?
        ''', (identity.batch_id, identity.row_id)).fetchone()
        if record is None:
            return None
        ticket = self.tickets.get(connection, record['ticket_id'])
        return AssignmentStatus(ticket, record['confirmed_receipt'], record['reserved_order'])

    def read_current(self, identity: RowIdentity) -> AssignmentStatus | None:
        """Read the current assignment from the coordination database.

        Used while another database (a warehouse ledger) holds its own writer
        lock, so the coordination connection is opened independently.
        """
        with self.database.read() as reader:
            return self.get_current(identity, connection=reader)

    def list_open_tickets(self, connection: sqlite3.Connection, batch_id: str,
                          warehouse: str) -> tuple[int, ...]:
        records = connection.execute('''
            SELECT a.ticket_id FROM assignments AS a
            JOIN tickets AS t ON t.ticket_id = a.ticket_id
            JOIN manifest_rows AS m ON m.batch_id = a.batch_id AND m.row_id = a.row_id
            WHERE a.batch_id = ? AND t.warehouse = ?
              AND a.confirmed_receipt IS NULL AND a.reserved_order IS NULL
            ORDER BY m.position
        ''', (batch_id, warehouse))
        return tuple(record['ticket_id'] for record in records)

    def confirm_receipt(self, receipt: Receipt) -> bool:
        with self.database.write() as connection:
            cursor = connection.execute('''
                UPDATE assignments SET confirmed_receipt = ?
                WHERE batch_id = ? AND row_id = ? AND ticket_id = ?
                  AND EXISTS (SELECT 1 FROM tickets AS t
                              WHERE t.ticket_id = assignments.ticket_id AND t.warehouse = ?)
                  AND (confirmed_receipt IS NULL OR confirmed_receipt = ?)
            ''', (receipt.receipt_id, receipt.identity.batch_id, receipt.identity.row_id,
                  receipt.ticket_id, receipt.warehouse, receipt.receipt_id))
            return cursor.rowcount == 1
