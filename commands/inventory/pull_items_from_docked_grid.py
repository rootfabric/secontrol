#!/usr/bin/env python3
"""
Script to pull items from grid to base - works even with merge block connections.

Usage:
    python examples/organized/container/advanced/pull_items_from_docked_grid.py \
        --source-grid skynet-baza1 --target-grid skynet-farpost0 --force
"""

from __future__ import annotations

import time
import argparse
import sys

from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.devices.ship_drill_device import ShipDrillDevice
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.common import resolve_owner_id
from secontrol.redis_client import RedisEventClient
from secontrol import Grid


DEFAULT_SOURCE = "skynet-baza1"
DEFAULT_TARGET = "skynet-farpost0"


def get_container_or_default(containers: list[ContainerDevice], name: str | None) -> ContainerDevice | None:
    if name:
        for c in containers:
            if c.name == name:
                return c
    return containers[0] if containers else None


def select_available_container(containers: list[ContainerDevice], current: ContainerDevice) -> ContainerDevice:
    current.send_command({"cmd": "update"})
    time.sleep(0.1)
    cap = current.capacity()
    if cap['fillRatio'] < 1.0:
        return current
    for cont in containers:
        if cont.device_id == current.device_id:
            continue
        cont.send_command({"cmd": "update"})
        time.sleep(0.1)
        cap = cont.capacity()
        if cap['fillRatio'] < 1.0:
            print(f"  Switch to container: {cont.name}", file=sys.stderr)
            return cont
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull items from docked grid to base.")
    parser.add_argument("--source-grid", default=DEFAULT_SOURCE, help="Source grid name (items will be taken from)")
    parser.add_argument("--target-grid", default=DEFAULT_TARGET, help="Target grid name (items will go to)")
    parser.add_argument("--source-container", default=None, help="Source container name (default: first found)")
    parser.add_argument("--target-container", default=None, help="Target container name (default: first found)")
    parser.add_argument("--dry-run", action="store_true", help="Show state only, do not transfer")
    parser.add_argument("--force", action="store_true", help="Force transfer even if connector check fails (for merged grids)")
    args = parser.parse_args()

    owner_id = resolve_owner_id()
    client = RedisEventClient()

    try:
        grids = client.list_grids(owner_id)
        if not grids:
            print("No grids found.")
            return

        source_info = None
        target_info = None
        for g in grids:
            name = g.get('name', '')
            if name == args.source_grid:
                source_info = g
            elif name == args.target_grid:
                target_info = g

        if source_info is None:
            print(f"Source grid '{args.source_grid}' not found.")
            print(f"Available grids: {[g.get('name') for g in grids]}")
            return
        if target_info is None:
            print(f"Target grid '{args.target_grid}' not found.")
            print(f"Available grids: {[g.get('name') for g in grids]}")
            return

        source_grid = Grid(client, owner_id, str(source_info['id']), owner_id, name=source_info['name'])
        target_grid = Grid(client, owner_id, str(target_info['id']), owner_id, name=target_info['name'])

        print(f"=== DIAGNOSTIC ===")
        print(f"Source: {source_info['name']} (id={source_info['id']})")
        print(f"Target: {target_info['name']} (id={target_info['id']})")

        print(f"\n--- Connectors on {source_info['name']} ---")
        for c in source_grid.find_devices_by_type(ConnectorDevice):
            c.send_command({"cmd": "update"})
        time.sleep(0.3)
        for c in source_grid.find_devices_by_type(ConnectorDevice):
            status = c.telemetry.get('connectorStatus', 'Unknown')
            other_id = c.telemetry.get('otherConnectorGridId')
            print(f"  {c.name}: status={status}, otherGridId={other_id}")

        print(f"\n--- Connectors on {target_info['name']} ---")
        for c in target_grid.find_devices_by_type(ConnectorDevice):
            c.send_command({"cmd": "update"})
        time.sleep(0.3)
        for c in target_grid.find_devices_by_type(ConnectorDevice):
            status = c.telemetry.get('connectorStatus', 'Unknown')
            other_id = c.telemetry.get('otherConnectorGridId')
            print(f"  {c.name}: status={status}, otherGridId={other_id}")

        source_containers = list(source_grid.find_devices_by_type(ContainerDevice))
        target_containers = list(target_grid.find_devices_by_type(ContainerDevice))

        print(f"\n--- Inventories on {source_info['name']} ---")
        for cont in source_containers:
            cont.send_command({"cmd": "update"})
        time.sleep(0.3)
        for cont in source_containers:
            items = cont.items()
            if items:
                print(f"  {cont.name}: {len(items)} item types")
                for item in items:
                    print(f"    - {item.amount:,.0f} x {item.display_name or item.subtype}")
            else:
                print(f"  {cont.name}: empty")

        print(f"\n--- Refineries on {source_info['name']} ---")
        for ref in source_grid.find_devices_by_type(RefineryDevice):
            ref.send_command({"cmd": "update"})
        time.sleep(0.3)
        for ref in source_grid.find_devices_by_type(RefineryDevice):
            print(f"  {ref.name}:")
            for inv_name, inv in [("input", ref.input_inventory()), ("output", ref.output_inventory())]:
                items = inv.items if inv else []
                if items:
                    print(f"    {inv_name}:")
                    for item in items:
                        print(f"      {item.amount:,.0f} x {item.display_name or item.subtype}")
                else:
                    print(f"    {inv_name}: empty")

        print(f"\n--- Assemblers on {source_info['name']} ---")
        for asm in source_grid.find_devices_by_type("assembler"):
            asm.send_command({"cmd": "update"})
        time.sleep(0.3)
        for asm in source_grid.find_devices_by_type("assembler"):
            items = asm.items()
            if items:
                print(f"  {asm.name}:")
                for item in items:
                    print(f"    {item.amount:,.0f} x {item.display_name or item.subtype}")
            else:
                print(f"  {asm.name}: empty")

        print(f"\n--- Inventories on {target_info['name']} ---")
        for cont in target_containers:
            cont.send_command({"cmd": "update"})
        time.sleep(0.3)
        for cont in target_containers:
            items = cont.items()
            if items:
                print(f"  {cont.name}: {len(items)} item types")
                for item in items:
                    print(f"    - {item.amount:,.0f} x {item.display_name or item.subtype}")
            else:
                print(f"  {cont.name}: empty")

        source_connector = None
        for c in source_grid.find_devices_by_type(ConnectorDevice):
            other = c.telemetry.get("otherConnectorGridId")
            if other and str(other) != str(source_grid.grid_id):
                source_connector = c
                break

        if source_connector is None and not args.force:
            print("\n!!! PROBLEM: Connectors are NOT connected between grids !!!", file=sys.stderr)
            print("move_all() requires grids to be physically docked (connected via connectors).", file=sys.stderr)
            print("Use --force to attempt transfer anyway (for merge-block merged grids).", file=sys.stderr)
            return

        if args.dry_run:
            print("\n=== DRY RUN: no transfer performed ===")
            return

        target_container = get_container_or_default(target_containers, args.target_container)
        if target_container is None:
            print("Target container not found.")
            return

        total_transferred = 0

        all_source_devices = []
        all_source_devices.extend(source_grid.find_devices_by_type(ContainerDevice))
        all_source_devices.extend(source_grid.find_devices_by_type(CockpitDevice))
        all_source_devices.extend(source_grid.find_devices_by_type(ShipDrillDevice))
        all_source_devices.extend(source_grid.find_devices_by_type(RefineryDevice))

        for device in all_source_devices:
            device.send_command({"cmd": "update"})
            time.sleep(0.1)

            is_refinery = isinstance(device, RefineryDevice)
            source_inventories = [(None, None)]
            if is_refinery:
                input_inv = device.input_inventory()
                output_inv = device.output_inventory()
                source_inventories = []
                if input_inv and input_inv.items:
                    source_inventories.append(("input", input_inv))
                if output_inv and output_inv.items:
                    source_inventories.append(("output", output_inv))
                if not source_inventories:
                    source_inventories = [(None, None)]

            for inv_label, source_inv in source_inventories:
                inv_desc = f" ({inv_label})" if inv_label else ""
                items = device.items(source_inv) if source_inv else device.items()
                if not items:
                    continue

                print(f"\n>>> Transfer from '{device.name}'{inv_desc}:")
                for item in items:
                    print(f"    {item.amount:,.0f} x {item.display_name or item.subtype}")

                target_container = select_available_container(target_containers, target_container)

                try:
                    result = device.move_all(target_container, source_inventory=source_inv)
                    time.sleep(0.5)
                    device.send_command({"cmd": "update"})
                    time.sleep(0.1)
                    remaining = device.items(source_inv) if source_inv else device.items()

                    if result > 0:
                        total_transferred += result
                        print(f"    [OK] Transferred {result} type(s)")
                    else:
                        print(f"    [!!] Command sent but server did not confirm transfer")

                    if remaining:
                        print(f"    [!!] REMAINING in source:")
                        for item in remaining:
                            print(f"        {item.amount:,.0f} x {item.display_name or item.subtype}")
                except Exception as exc:
                    print(f"    [ERROR] {exc}")

        print(f"\n=== TOTAL: transferred {total_transferred} type(s) ===")

        if total_transferred == 0:
            print("If grids are docked but transfer fails - try reconnecting connectors manually.")
            print("Disconnect and reconnect the ship connector to force refresh.")

    finally:
        client.close()


if __name__ == "__main__":
    main()