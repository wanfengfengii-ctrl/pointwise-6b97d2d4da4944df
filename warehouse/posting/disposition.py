from dataclasses import dataclass

from warehouse.dispatch.tickets import DeliveryTicket
from warehouse.posting.receipts import Receipt


@dataclass(frozen=True)
class PostingObservation:
    ticket: DeliveryTicket
    receipt: Receipt | None

    def __post_init__(self) -> None:
        receipt = self.receipt
        if receipt is not None and (receipt.ticket_id, receipt.identity, receipt.warehouse) != (
            self.ticket.ticket_id, self.ticket.identity, self.ticket.warehouse
        ):
            raise ValueError("receipt does not belong to the observed ticket")
