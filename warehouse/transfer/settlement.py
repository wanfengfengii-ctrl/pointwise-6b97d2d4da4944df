from collections.abc import Mapping

from warehouse.dispatch.tickets import DeliveryTicket
from warehouse.posting.disposition import PostingObservation
from warehouse.posting.ledger import PostingLedger, WarehouseUnavailable
from warehouse.posting.receipts import Receipt


def probe_old_tickets(ledger: PostingLedger, tickets: tuple[DeliveryTicket, ...]
                      ) -> tuple[PostingObservation, ...] | None:
    observations = []
    for ticket in tickets:
        try:
            observations.append(ledger.probe_ticket(ticket))
        except WarehouseUnavailable:
            return None
    return tuple(observations)


def classify_transfer_rows(tickets: tuple[DeliveryTicket, ...],
                           observations: tuple[PostingObservation, ...],
                           confirmed: Mapping[int, str]
                           ) -> tuple[tuple[Receipt, ...], tuple[DeliveryTicket, ...]]:
    if tuple(observation.ticket for observation in observations) != tickets:
        raise ValueError("old warehouse observations do not cover the bound tickets in order")
    retained = []
    movable = []
    for observation in observations:
        ticket = observation.ticket
        receipt = observation.receipt
        if receipt is not None and confirmed.get(ticket.ticket_id) == receipt.receipt_id:
            retained.append(receipt)
        else:
            movable.append(ticket)
    return tuple(retained), tuple(movable)
