from collections.abc import Callable
import sqlite3

from warehouse.dispatch.status import DispatchStatusStore
from warehouse.dispatch.tickets import DeliveryTicket, require_warehouse
from warehouse.posting.admission import Admission, admit_delivery, verify_ticket
from warehouse.posting.disposition import PostingObservation
from warehouse.posting.receipts import Receipt, find_receipt, initialize_receipts, save_receipt
from warehouse.source.manifest import ManifestStore
from warehouse.source.rows import encode_liters
from warehouse.storage import Database


class WarehouseUnavailable(RuntimeError):
    pass


class PostingLedger:
    def __init__(self, warehouse: str, database: Database, manifests: ManifestStore,
                 status: DispatchStatusStore):
        require_warehouse(warehouse)
        self.warehouse = warehouse
        self.database = database
        self.manifests = manifests
        self.status = status

    def initialize_schema(self) -> None:
        with self.database.write(create=True) as connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS posted_rows (
                    posting_number INTEGER PRIMARY KEY,
                    ticket_id INTEGER NOT NULL UNIQUE,
                    batch_id TEXT NOT NULL,
                    row_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    liters BLOB NOT NULL,
                    UNIQUE (batch_id, row_id)
                )
            ''')
            initialize_receipts(connection)

    def post(self, ticket: DeliveryTicket, *,
             after_admission: Callable[[Admission], None] | None = None,
             before_commit: Callable[[Receipt], None] | None = None,
             after_commit: Callable[[Receipt], None] | None = None) -> Receipt:
        admission = admit_delivery(self.manifests, self.status, self.warehouse, ticket)
        if after_admission is not None:
            after_admission(admission)
        row = admission.row
        ticket_id = admission.ticket.ticket_id
        with self.database.write() as connection:
            receipt = find_receipt(connection, self.warehouse, ticket_id)
            if receipt is None:
                cursor = connection.execute('''
                    INSERT INTO posted_rows (ticket_id, batch_id, row_id, origin, liters)
                    VALUES (?, ?, ?, ?, ?)
                ''', (ticket_id, row.identity.batch_id, row.identity.row_id,
                      row.origin, encode_liters(row.liters)))
                receipt = save_receipt(connection, self.warehouse, ticket_id, row.identity,
                                       cursor.lastrowid)
                if before_commit is not None:
                    before_commit(receipt)
        if after_commit is not None:
            after_commit(receipt)
        return receipt

    def probe_ticket(self, ticket: DeliveryTicket) -> PostingObservation:
        with self.status.database.read() as reader:
            published = verify_ticket(reader, self.status.tickets, self.warehouse, ticket)
        try:
            with self.database.write() as connection:
                receipt = find_receipt(connection, self.warehouse, published.ticket_id)
                return PostingObservation(published, receipt)
        except sqlite3.OperationalError as error:
            code = getattr(error, 'sqlite_errorcode', 0) & 0xff
            if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_CANTOPEN,
                        sqlite3.SQLITE_READONLY, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_FULL}:
                raise WarehouseUnavailable(f'{self.warehouse} outcome is temporarily unavailable') from error
            raise
