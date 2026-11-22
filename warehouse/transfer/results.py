from dataclasses import dataclass
import json
import sqlite3

from warehouse.dispatch.tickets import DeliveryTicket, TicketStore
from warehouse.posting.receipts import Receipt
from warehouse.source.rows import RowIdentity
from warehouse.storage import Database


@dataclass(frozen=True)
class TransferResult:
    order_id: str
    state: str
    retained: tuple[Receipt, ...] = ()
    moved: tuple[DeliveryTicket, ...] = ()


class TransferResultStore:
    def __init__(self, database: Database, tickets: TicketStore):
        self.database = database
        self.tickets = tickets

    def initialize_schema(self) -> None:
        with self.database.write() as connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS transfer_results (
                    order_id TEXT PRIMARY KEY NOT NULL REFERENCES transfer_orders(order_id),
                    retained TEXT NOT NULL,
                    moved_ticket_ids TEXT NOT NULL
                )
            ''')

    def save_result(self, connection: sqlite3.Connection, result: TransferResult) -> None:
        if result.state != 'completed':
            raise ValueError('only completed transfer results are stored')
        retained = [
            [receipt.receipt_id, receipt.identity.batch_id, receipt.identity.row_id,
             receipt.warehouse, receipt.ticket_id]
            for receipt in result.retained
        ]
        moved_ids = [ticket.ticket_id for ticket in result.moved]
        connection.execute('INSERT INTO transfer_results VALUES (?, ?, ?)',
                           (result.order_id, json.dumps(retained), json.dumps(moved_ids)))

    def load_result(self, connection: sqlite3.Connection, order_id: str) -> TransferResult:
        record = connection.execute('SELECT * FROM transfer_results WHERE order_id = ?',
                                    (order_id,)).fetchone()
        if record is None:
            raise LookupError(f'no completed result for transfer {order_id!r}')
        retained = tuple(
            Receipt(receipt_id, RowIdentity(batch_id, row_id), warehouse, ticket_id)
            for receipt_id, batch_id, row_id, warehouse, ticket_id in json.loads(record['retained'])
        )
        moved = tuple(self.tickets.get(connection, ticket_id)
                      for ticket_id in json.loads(record['moved_ticket_ids']))
        return TransferResult(order_id, 'completed', retained, moved)
