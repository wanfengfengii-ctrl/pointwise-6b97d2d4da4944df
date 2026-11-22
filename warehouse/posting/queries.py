from dataclasses import dataclass

from warehouse.dispatch.tickets import require_warehouse
from warehouse.posting.receipts import Receipt, find_receipt
from warehouse.source.rows import RowIdentity, decode_liters
from warehouse.storage import Database


@dataclass(frozen=True)
class PostedRow:
    identity: RowIdentity
    warehouse: str
    receipt_id: str
    origin: str
    liters: int
    ticket_id: int


class WarehouseQueries:
    def __init__(self, warehouse: str, database: Database):
        require_warehouse(warehouse)
        self.warehouse = warehouse
        self.database = database

    def list_postings(self, batch_id: str) -> tuple[PostedRow, ...]:
        with self.database.read() as connection:
            records = connection.execute('''
                SELECT p.row_id, p.origin, p.liters, p.ticket_id, r.receipt_id
                FROM posted_rows AS p LEFT JOIN receipts AS r USING (posting_number, ticket_id)
                WHERE p.batch_id = ? ORDER BY p.posting_number
            ''', (batch_id,))
            postings = []
            for record in records:
                if record['receipt_id'] is None:
                    raise ValueError(f'posting for ticket {record["ticket_id"]} has no receipt')
                postings.append(PostedRow(
                    RowIdentity(batch_id, record['row_id']), self.warehouse,
                    record['receipt_id'], record['origin'], decode_liters(record['liters']),
                    record['ticket_id'],
                ))
            return tuple(postings)

    def get_receipt(self, ticket_id: int) -> Receipt | None:
        with self.database.read() as connection:
            return find_receipt(connection, self.warehouse, ticket_id)
