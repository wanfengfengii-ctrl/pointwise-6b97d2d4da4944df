from dataclasses import dataclass
from sqlite3 import Connection

from warehouse.dispatch.status import DispatchStatusStore
from warehouse.dispatch.tickets import DeliveryTicket, TicketStore
from warehouse.source.manifest import ManifestStore
from warehouse.source.rows import SourceRow


class DeliveryRejected(ValueError):
    pass


@dataclass(frozen=True)
class Admission:
    ticket: DeliveryTicket
    row: SourceRow


def verify_ticket(connection: Connection, store: TicketStore, warehouse: str,
                  ticket: DeliveryTicket) -> DeliveryTicket:
    if not isinstance(ticket, DeliveryTicket) or type(ticket.ticket_id) is not int:
        raise DeliveryRejected('a published delivery ticket is required')
    try:
        published = store.get(connection, ticket.ticket_id)
    except LookupError as error:
        raise DeliveryRejected(str(error)) from error
    if published != ticket or published.warehouse != warehouse:
        raise DeliveryRejected(f'ticket {ticket.ticket_id} does not match warehouse {warehouse!r}')
    return published


def admit_delivery(manifests: ManifestStore, status: DispatchStatusStore,
                   warehouse: str, ticket: DeliveryTicket) -> Admission:
    with status.database.read() as connection:
        published = verify_ticket(connection, status.tickets, warehouse, ticket)
        current = status.get_current(published.identity, connection=connection)
        if current is None or current.ticket != published:
            raise DeliveryRejected(f'ticket {published.ticket_id} is no longer assigned')
        row, = manifests.select_rows(published.identity.batch_id, (published.identity.row_id,),
                                     connection=connection)
        return Admission(published, row)
