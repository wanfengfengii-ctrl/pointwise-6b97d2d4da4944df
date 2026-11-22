from collections.abc import Callable, Iterable, Mapping

from warehouse.dispatch.assignment import AssignmentStore
from warehouse.dispatch.tickets import require_warehouse
from warehouse.posting.ledger import PostingLedger
from warehouse.source.manifest import selection_ids
from warehouse.source.validation import require_text
from warehouse.transfer.progress import TransferParameters, TransferProgressStore
from warehouse.transfer.results import TransferResult, TransferResultStore
from warehouse.transfer.settlement import classify_transfer_rows, probe_old_tickets


class TransferConflict(ValueError):
    pass


class TransferService:
    def __init__(self, assignments: AssignmentStore, ledgers: Mapping[str, PostingLedger]):
        self.assignments = assignments
        self.ledgers = ledgers
        self.database = assignments.database
        self.progress = TransferProgressStore(self.database)
        self.results = TransferResultStore(self.database, assignments.tickets)

    def initialize_schema(self) -> None:
        self.progress.initialize_schema()
        self.results.initialize_schema()

    def transfer(self, order_id: str, batch_id: str, row_ids: Iterable[str],
                 source: str, destination: str, *,
                 before_publish_commit: Callable[[TransferResult], None] | None = None
                 ) -> TransferResult:
        require_text(order_id, 'order_id')
        require_text(batch_id, 'batch_id')
        require_warehouse(source)
        require_warehouse(destination)
        if source == destination:
            raise ValueError('transfer requires different warehouses')
        parameters = TransferParameters(batch_id, selection_ids(row_ids), source, destination)
        with self.database.write() as connection:
            order = self.progress.get_order(connection, order_id)
            if order is None:
                tickets = self.assignments.reserve_transfer(connection, order_id, batch_id,
                                                            parameters.row_ids, source)
                order = self.progress.start_order(connection, order_id, parameters, tickets)
            elif order.parameters != parameters:
                raise TransferConflict(f'transfer {order_id!r} has different parameters')
            elif order.state == 'completed':
                return self.results.load_result(connection, order_id)
            tickets = tuple(self.assignments.tickets.get(connection, ticket_id)
                            for ticket_id in order.old_ticket_ids)

            confirmed = {}
            for ticket in tickets:
                status = self.assignments.status.get_current(ticket.identity, connection=connection)
                if status is not None and status.ticket == ticket and status.confirmed_receipt is not None:
                    confirmed[ticket.ticket_id] = status.confirmed_receipt

        observations = probe_old_tickets(self.ledgers[source], tickets)
        with self.database.write() as connection:
            current = self.progress.get_order(connection, order_id)
            if current is None or current.old_ticket_ids != order.old_ticket_ids:
                raise RuntimeError(f'transfer {order_id!r} lost its bound scope')
            if current.state == 'completed':
                return self.results.load_result(connection, order_id)
            if observations is None:
                self.progress.mark_pending(connection, order_id)
                return TransferResult(order_id, 'pending')
            retained, movable = classify_transfer_rows(tickets, observations, confirmed)
            moved = self.assignments.publish_transfer(connection, order_id, retained, movable,
                                                      destination)
            result = TransferResult(order_id, 'completed', retained, moved)
            self.results.save_result(connection, result)
            self.progress.mark_completed(connection, order_id)
            if before_publish_commit is not None:
                before_publish_commit(result)
            return result
