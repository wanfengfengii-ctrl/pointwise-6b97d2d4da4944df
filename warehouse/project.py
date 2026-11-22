from collections.abc import Callable, Iterable
from pathlib import Path

from warehouse.audit.report import AuditReport, audit
from warehouse.dispatch.assignment import AssignmentStore
from warehouse.dispatch.delivery import deliver_ticket
from warehouse.dispatch.queue import list_pending_tickets
from warehouse.dispatch.tickets import DeliveryTicket, WAREHOUSES, require_warehouse
from warehouse.posting.admission import Admission
from warehouse.posting.ledger import PostingLedger
from warehouse.posting.queries import WarehouseQueries
from warehouse.posting.receipts import Receipt
from warehouse.source.intake import ManifestDraft
from warehouse.source.manifest import ManifestStore
from warehouse.source.rows import SealedManifest
from warehouse.source.seal import seal
from warehouse.storage import Database
from warehouse.transfer.orders import TransferService
from warehouse.transfer.results import TransferResult


class WarehouseProject:
    """Public workflow over a work directory with three independent databases."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).absolute()
        self.coordination = Database(self.directory / 'coordination.sqlite3')
        self.manifests = ManifestStore(self.coordination)
        self.assignments = AssignmentStore(self.coordination, self.manifests)
        self.ledgers = {}
        self.queries = {}
        for warehouse in WAREHOUSES:
            database = Database(self.directory / f'{warehouse}.sqlite3')
            self.ledgers[warehouse] = PostingLedger(warehouse, database, self.manifests,
                                                    self.assignments.status)
            self.queries[warehouse] = WarehouseQueries(warehouse, database)
        self.transfers = TransferService(self.assignments, self.ledgers)

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifests.initialize_schema()
        self.assignments.initialize_schema()
        self.transfers.initialize_schema()
        for ledger in self.ledgers.values():
            ledger.initialize_schema()

    def seal(self, draft: ManifestDraft) -> SealedManifest:
        return seal(self.manifests, draft)

    def dispatch(self, request_id: str, batch_id: str, row_ids: Iterable[str],
                 warehouse: str) -> tuple[DeliveryTicket, ...]:
        return self.assignments.dispatch(request_id, batch_id, row_ids, warehouse)

    def pending(self, warehouse: str, batch_id: str) -> tuple[DeliveryTicket, ...]:
        return list_pending_tickets(self.assignments.status, warehouse, batch_id)

    def post(self, warehouse: str, ticket: DeliveryTicket, *,
             after_admission: Callable[[Admission], None] | None = None,
             before_commit: Callable[[Receipt], None] | None = None,
             after_commit: Callable[[Receipt], None] | None = None) -> Receipt:
        require_warehouse(warehouse)
        return deliver_ticket(self.ledgers[warehouse], self.assignments.status, ticket,
                              after_admission=after_admission, before_commit=before_commit,
                              after_commit=after_commit)

    def transfer(self, order_id: str, batch_id: str, row_ids: Iterable[str],
                 source: str, destination: str, *,
                 before_publish_commit: Callable[[TransferResult], None] | None = None
                 ) -> TransferResult:
        return self.transfers.transfer(order_id, batch_id, row_ids, source, destination,
                                       before_publish_commit=before_publish_commit)

    def audit(self, batch_id: str) -> AuditReport:
        return audit(self.manifests, self.queries.values(), batch_id)
