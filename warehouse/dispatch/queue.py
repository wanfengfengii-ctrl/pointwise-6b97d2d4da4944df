from warehouse.dispatch.status import DispatchStatusStore
from warehouse.dispatch.tickets import DeliveryTicket, require_warehouse
from warehouse.source.manifest import UnknownManifest


def list_pending_tickets(status: DispatchStatusStore, warehouse: str,
                         batch_id: str) -> tuple[DeliveryTicket, ...]:
    require_warehouse(warehouse)
    with status.database.read() as connection:
        found = connection.execute(
            'SELECT 1 FROM manifests WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        if found is None:
            raise UnknownManifest(f'unknown manifest {batch_id!r}')
        ticket_ids = status.list_open_tickets(connection, batch_id, warehouse)
        return tuple(status.tickets.get(connection, ticket_id) for ticket_id in ticket_ids)
