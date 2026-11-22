from dataclasses import dataclass
import sqlite3

from warehouse.source.rows import RowIdentity


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    identity: RowIdentity
    warehouse: str
    ticket_id: int


def initialize_receipts(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            ticket_id INTEGER PRIMARY KEY,
            posting_number INTEGER NOT NULL UNIQUE REFERENCES posted_rows(posting_number),
            receipt_id TEXT NOT NULL UNIQUE
        )
    ''')


def find_receipt(connection: sqlite3.Connection, warehouse: str,
                 ticket_id: int) -> Receipt | None:
    record = connection.execute('''
        SELECT r.receipt_id, p.batch_id, p.row_id
        FROM receipts AS r JOIN posted_rows AS p USING (posting_number, ticket_id)
        WHERE r.ticket_id = ?
    ''', (ticket_id,)).fetchone()
    if record is None:
        return None
    return Receipt(record['receipt_id'], RowIdentity(record['batch_id'], record['row_id']),
                   warehouse, ticket_id)


def save_receipt(connection: sqlite3.Connection, warehouse: str, ticket_id: int,
                 identity: RowIdentity, posting_number: int) -> Receipt:
    receipt = Receipt(f'{warehouse}-{posting_number}', identity, warehouse, ticket_id)
    connection.execute('INSERT INTO receipts VALUES (?, ?, ?)',
                       (ticket_id, posting_number, receipt.receipt_id))
    return receipt
