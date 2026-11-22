from warehouse.dispatch.tickets import DeliveryTicket
from warehouse.posting.disposition import PostingObservation
from warehouse.posting.ledger import WarehouseUnavailable
from warehouse.posting.receipts import Receipt


def probe_old_tickets(ledger, tickets: tuple[DeliveryTicket, ...]
                      ) -> tuple[PostingObservation, ...] | None:
    observations = []
    for ticket in tickets:
        try:
            observations.append(ledger.probe_ticket(ticket))
        except WarehouseUnavailable:
            return None
    return tuple(observations)


def classify_transfer_rows(tickets: tuple[DeliveryTicket, ...],
                           observations: tuple[PostingObservation, ...]
                           ) -> tuple[tuple[Receipt, ...], tuple[DeliveryTicket, ...]]:
    """Settle each bound ticket from its durable in-warehouse outcome.

    A receipt already committed inside the source warehouse keeps the row in
    the original warehouse with its original receipt account, even when the
    coordination ledger never recorded the confirmation (a lost reply). Rows
    without a durable receipt have lost their eligibility once the old ticket
    is stopped, so they move to the destination on a freshly issued ticket.
    """
    if tuple(observation.ticket for observation in observations) != tickets:
        raise ValueError("old warehouse observations do not cover the bound tickets in order")
    retained = []
    movable = []
    for observation in observations:
        if observation.receipt is not None:
            retained.append(observation.receipt)
        else:
            movable.append(observation.ticket)
    return tuple(retained), tuple(movable)
