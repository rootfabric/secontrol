from __future__ import annotations

import time
from typing import Dict, Any, List

from secontrol import Grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.common import resolve_owner_id, resolve_player_id
from secontrol.redis_client import RedisEventClient


def run_for_grid(client: RedisEventClient, owner_id: str, player_id: str, grid_info: Dict[str, Any]) -> None:
    grid_id = str(grid_info.get('id'))
    grid_name = grid_info.get('name', 'unnamed')
    print(f"Starting connector demo for grid {grid_id} ({grid_name})")

    grid = Grid(client, owner_id, grid_id, player_id)

    connectors = list(grid.find_devices_by_type(ConnectorDevice))
    print(f"Found {len(connectors)} connector device(s) on grid {grid_name}:")

    for i, conn in enumerate(connectors, 1):
        print(f"  {i}. {conn.name or 'Connector'} (ID: {conn.device_id})")

    if not connectors:
        print("No connectors found, skipping.")
        return

    # Demonstrate all connector capabilities
    for conn in connectors:
        print(f"\n--- Demonstrating {conn.name or 'Connector'} (ID: {conn.device_id}) ---")

        # 1. Show current telemetry
        print("Current telemetry:")
        if conn.telemetry:
            for key, value in conn.telemetry.items():
                print(f"  {key}: {value}")
        else:
            print("  No telemetry available yet")

        # 2. Enable/Disable
        print("Testing enable/disable...")
        conn.enable()
        time.sleep(1)
        conn.disable()
        time.sleep(1)

        # 3. Connect/Disconnect
        print("Testing connect/disconnect...")
        conn.connect()
        time.sleep(2)
        conn.disconnect()
        time.sleep(1)

        # 4. Toggle connect
        print("Testing toggle_connect...")
        conn.toggle_connect()
        time.sleep(2)

        # 5. Set throw out
        print("Testing set_throw_out...")
        conn.set_throw_out(True)
        time.sleep(1)
        conn.set_throw_out(False)
        time.sleep(1)

        # 6. Set collect all
        print("Testing set_collect_all...")
        conn.set_collect_all(True)
        time.sleep(1)
        conn.set_collect_all(False)
        time.sleep(1)

        # 7. Scan for nearby connectors
        print("Testing scan...")
        conn.scan(100.0)
        print("Scan command sent. Results should appear in telemetry or logs.")
        time.sleep(2)

        # 8. Show inventory items
        items = conn.inventory_items()
        print(f"Connector has {len(items)} item types in inventory:")
        for item in items[:5]:  # Show first 5
            print(f"  {item.amount} x {item.display_name or item.subtype}")
        if len(items) > 5:
            print(f"  ... and {len(items) - 5} more")

    # 9. Remote transfer demonstration
    if len(connectors) >= 2:
        print("\n--- Demonstrating remote transfer ---")
        source = connectors[0]
        target = connectors[1]

        print(f"Source: {source.name or 'Connector'} (ID: {source.device_id})")
        print(f"Target: {target.name or 'Connector'} (ID: {target.device_id})")

        # Get some items from source
        source_items = source.inventory_items()
        if source_items:
            # Take first item for transfer
            item = source_items[0]
            transfer_items = [{
                "subtype": item.subtype,
                "type": item.type,
                "amount": min(10, item.amount)  # Transfer up to 10
            }]

            print(f"Attempting to transfer: {transfer_items[0]['amount']} x {item.display_name or item.subtype}")

            source.transfer_remote(int(target.device_id), transfer_items, 100.0)
            print("Remote transfer command sent.")
            time.sleep(3)

            # Check if transfer succeeded (by checking inventories again)
            print("Checking inventories after transfer...")
            source_items_after = source.inventory_items()
            target_items_after = target.inventory_items()

            source_count = sum(i.amount for i in source_items_after if i.subtype == item.subtype)
            target_count = sum(i.amount for i in target_items_after if i.subtype == item.subtype)

            print(f"Source now has: {source_count} x {item.display_name or item.subtype}")
            print(f"Target now has: {target_count} x {item.display_name or item.subtype}")
        else:
            print("Source connector has no items to transfer.")
    else:
        print("Need at least 2 connectors for remote transfer demo.")

    print(f"\nConnector demo for grid {grid_name} completed.")


def main() -> None:
    owner_id = resolve_owner_id()
    player_id = resolve_player_id(owner_id)
    print(f"Owner ID: {owner_id}")

    client = RedisEventClient()

    try:
        grids = client.list_grids(owner_id)
        if not grids:
            print("No grids found.")
            return

        print(f"Found {len(grids)} grids.")

        for grid_info in grids:
            print(f"Processing grid: {grid_info.get('name', 'unnamed')} (ID: {grid_info.get('id')})")
            run_for_grid(client, owner_id, player_id, grid_info)
            time.sleep(5)  # Pause between grids

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
