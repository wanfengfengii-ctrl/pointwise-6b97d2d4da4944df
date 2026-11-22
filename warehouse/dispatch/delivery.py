from collections.abc import Callable

from warehouse.dispatch.status import DispatchStatusStore
from warehouse.dispatch.tickets import DeliveryTicket
from warehouse.posting.admission import Admission
from warehouse.posting.ledger import PostingLedger
from warehouse.posting.receipts import Receipt


def deliver_ticket(ledger: PostingLedger, status: DispatchStatusStore, ticket: DeliveryTicket, *,
                   after_admission: Callable[[Admission], None] | None = None,
                   before_commit: Callable[[Receipt], None] | None = None,
                   after_commit: Callable[[Receipt], None] | None = None) -> Receipt:
    receipt = ledger.post(ticket, after_admission=after_admission,
                          before_commit=before_commit, after_commit=after_commit)
    status.confirm_receipt(receipt)
    return receipt
