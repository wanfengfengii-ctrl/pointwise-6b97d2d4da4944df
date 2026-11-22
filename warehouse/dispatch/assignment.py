from collections.abc import Iterable
import sqlite3

from warehouse.dispatch.requests import DispatchRequest, DispatchRequestStore
from warehouse.dispatch.status import DispatchStatusStore
from warehouse.dispatch.tickets import DeliveryTicket, TicketStore, require_warehouse
from warehouse.posting.receipts import Receipt
from warehouse.source.manifest import ManifestStore, selection_ids
from warehouse.source.validation import require_text
from warehouse.storage import Database


class AssignmentConflict(ValueError):
    pass


class AssignmentStore:
    def __init__(self, database: Database, manifests: ManifestStore):
        self.database = database
        self.manifests = manifests
        self.tickets = TicketStore()
        self.status = DispatchStatusStore(database, self.tickets)
        self.requests = DispatchRequestStore()

    def initialize_schema(self) -> None:
        with self.database.write() as connection:
            self.tickets.initialize_schema(connection)
            self.status.initialize_schema(connection)
            self.requests.initialize_schema(connection)

    def dispatch(self, request_id: str, batch_id: str, row_ids: Iterable[str],
                 warehouse: str) -> tuple[DeliveryTicket, ...]:
        require_text(request_id, 'request_id')
        require_text(batch_id, 'batch_id')
        require_warehouse(warehouse)
        request = DispatchRequest(batch_id, selection_ids(row_ids), warehouse)
        with self.database.write() as connection:
            existing = self.requests.lookup_request(connection, request_id)
            if existing is not None:
                original, ticket_ids = existing
                if original != request:
                    raise AssignmentConflict(f'dispatch {request_id!r} has different parameters')
                return tuple(self.tickets.get(connection, ticket_id) for ticket_id in ticket_ids)
            rows = self.manifests.select_rows(batch_id, request.row_ids, connection=connection)
            for row in rows:
                if self.status.get_current(row.identity, connection=connection) is not None:
                    raise AssignmentConflict(f'row {row.identity.row_id!r} already assigned')
            tickets = tuple(self.tickets.issue(connection, row.identity, warehouse, 1)
                            for row in rows)
            connection.executemany('''
                INSERT INTO assignments (batch_id, row_id, ticket_id) VALUES (?, ?, ?)
            ''', ((batch_id, ticket.identity.row_id, ticket.ticket_id) for ticket in tickets))
            self.requests.save_request(connection, request_id, request,
                                       tuple(ticket.ticket_id for ticket in tickets))
            return tickets

    def reserve_transfer(self, connection: sqlite3.Connection, order_id: str,
                         batch_id: str, row_ids: tuple[str, ...],
                         warehouse: str) -> tuple[DeliveryTicket, ...]:
        rows = self.manifests.select_rows(batch_id, row_ids, connection=connection)
        tickets = []
        for row in rows:
            status = self.status.get_current(row.identity, connection=connection)
            if status is None or status.ticket.warehouse != warehouse:
                raise AssignmentConflict(f'row {row.identity.row_id!r} is outside the old warehouse')
            if status.reserved_order is not None:
                raise AssignmentConflict(f'row {row.identity.row_id!r} is already reserved')
            tickets.append(status.ticket)
        connection.executemany('UPDATE assignments SET reserved_order = ? WHERE ticket_id = ?',
                               ((order_id, ticket.ticket_id) for ticket in tickets))
        return tuple(tickets)

    def publish_transfer(self, connection: sqlite3.Connection, order_id: str,
                         retained: tuple[Receipt, ...], movable: tuple[DeliveryTicket, ...],
                         destination: str) -> tuple[DeliveryTicket, ...]:
        for receipt in retained:
            self._finish_reservation(connection, order_id, receipt.ticket_id,
                                     receipt.ticket_id, receipt.receipt_id)
        new_tickets = []
        for old_ticket in movable:
            new_ticket = self.tickets.issue(connection, old_ticket.identity, destination,
                                            old_ticket.generation + 1)
            self._finish_reservation(connection, order_id, old_ticket.ticket_id,
                                     new_ticket.ticket_id, None)
            new_tickets.append(new_ticket)
        return tuple(new_tickets)

    def _finish_reservation(self, connection: sqlite3.Connection, order_id: str,
                            old_id: int, new_id: int, receipt_id: str | None) -> None:
        updated = connection.execute('''
            UPDATE assignments SET ticket_id = ?, confirmed_receipt = ?, reserved_order = NULL
            WHERE ticket_id = ? AND reserved_order = ?
        ''', (new_id, receipt_id, old_id, order_id))
        if updated.rowcount != 1:
            raise AssignmentConflict(f'order {order_id!r} lost reservation for ticket {old_id}')
