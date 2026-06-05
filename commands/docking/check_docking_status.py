from secontrol.common import resolve_owner_id
from secontrol.redis_client import RedisEventClient
from secontrol import Grid
from secontrol.devices.connector_device import ConnectorDevice

owner_id = resolve_owner_id()
client = RedisEventClient()

grids = client.list_grids(owner_id)
print(f"Found {len(grids)} grids:")
for g in grids:
    name = g.get("name", "unknown")
    gid = g.get("id", "unknown")
    print(f"  {name} (id={gid})")

    grid = Grid(client, owner_id, str(gid), owner_id, name=name)
    connectors = list(grid.find_devices_by_type(ConnectorDevice))
    if connectors:
        for c in connectors:
            c.send_command({"cmd": "update"})
        import time; time.sleep(0.5)
        for c in connectors:
            status = c.telemetry.get("connectorStatus", "Unknown")
            other_gid = c.telemetry.get("otherConnectorGridId")
            other_name = "None"
            if other_gid:
                for g2 in grids:
                    if str(g2.get("id")) == str(other_gid):
                        other_name = g2.get("name", "unknown")
                        break
            print(f"    Connector '{c.name}': status={status}, connected_to={other_name}(id={other_gid})")

client.close()