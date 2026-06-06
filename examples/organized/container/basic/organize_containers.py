#!/usr/bin/env python3
"""Universal container organization script.
Renames containers and organizes resources: ores -> ore container, components -> component container.
"""

from __future__ import annotations

import argparse
import sys
import os
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol.common import prepare_grid, close
from secontrol.inventory import InventoryItem


ORE_KEYWORDS = ["ore", "руда"]
INGOT_KEYWORDS = ["ingot", "слиток"]
COMPONENT_KEYWORDS = ["component", "компонент"]
STONE_KEYWORDS = ["stone", "камень", "gravel", "гравий"]


def is_ore(item_type: str, subtype: str) -> bool:
    text = f"{item_type} {subtype}".lower()
    return any(k in text for k in ORE_KEYWORDS) and not any(k in text for k in INGOT_KEYWORDS)


def is_ingot(item_type: str, subtype: str) -> bool:
    text = f"{item_type} {subtype}".lower()
    return any(k in text for k in INGOT_KEYWORDS)


def is_component(item_type: str, subtype: str) -> bool:
    text = f"{item_type} {subtype}".lower()
    return any(k in text for k in COMPONENT_KEYWORDS)


def is_stone(item_type: str, subtype: str) -> bool:
    text = f"{item_type} {subtype}".lower()
    return any(k in text for k in STONE_KEYWORDS)


def get_large_containers(grid):
    """Get all large cargo containers."""
    containers = grid.find_devices_containers()
    result = []
    for c in containers:
        if hasattr(c, 'name') and 'large cargo container' in c.name.lower():
            result.append(c)
    return result


def rename_container(container, new_name: str, dry_run: bool = False):
    """Rename a container using set_name command."""
    old_name = container.name
    if old_name == new_name:
        print(f"  Already named: {new_name}")
        return True
    if dry_run:
        print(f"  [DRY RUN] Would rename '{old_name}' -> '{new_name}'")
        return True
    try:
        sent = container.send_command({"cmd": "set_name", "name": new_name})
        if sent > 0:
            print(f"  Renamed: '{old_name}' -> '{new_name}'")
            time.sleep(0.5)  # Wait for telemetry update
            return True
        else:
            print(f"  ERROR renaming '{old_name}': command not sent")
            return False
    except Exception as e:
        print(f"  ERROR renaming '{old_name}': {e}")
        return False


def move_items_between(source, target, item_filter, dry_run: bool = False):
    """Move items matching filter from source to target using device.move_items."""
    source_inv = source.get_inventory()
    if not source_inv or not getattr(source_inv, 'items', None):
        return 0

    items_to_move = []
    for item in source_inv.items:
        if item_filter(item.type, item.subtype):
            items_to_move.append(InventoryItem(item.type, item.subtype, item.amount, item.display_name))

    if not items_to_move:
        return 0

    if dry_run:
        for item in items_to_move:
            print(f"    [DRY RUN] Would move {item.amount} x {item.subtype} from {source.name} to {target.name}")
        return len(items_to_move)

    try:
        moved_count = source.move_items(target, items_to_move)
        for item in items_to_move:
            print(f"    Moved {item.amount} x {item.subtype} -> {target.name}")
        return moved_count
    except Exception as e:
        print(f"    ERROR moving items: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Organize base containers: ores/components")
    parser.add_argument("--grid", required=True, help="Grid name (e.g., skynet-farpost0)")
    parser.add_argument("--ore-name", default="[Ore Storage]", help="Name for ore container")
    parser.add_argument("--component-name", default="[Component Storage]", help="Name for component container")
    parser.add_argument("--ingot-name", default="[Ingot Storage]", help="Name for ingot container (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without changes")
    parser.add_argument("--force-rename", action="store_true", help="Rename even if names match")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    try:
        print(f"=== Organizing containers on {grid.name} ===")
        if args.dry_run:
            print("*** DRY RUN MODE ***")

        # Find large cargo containers
        containers = get_large_containers(grid)
        print(f"\nFound {len(containers)} large cargo containers:")
        for c in containers:
            print(f"  - {c.name}")

        if len(containers) < 2:
            print("ERROR: Need at least 2 large cargo containers")
            return 1

        # Assign containers
        ore_container = containers[0]
        component_container = containers[1]
        ingot_container = containers[2] if len(containers) > 2 else None

        print(f"\nAssigning:")
        print(f"  Ore container: {ore_container.name}")
        print(f"  Component container: {component_container.name}")
        if ingot_container:
            print(f"  Ingot container: {ingot_container.name}")

        # Rename containers
        print(f"\n--- Renaming containers ---")
        rename_container(ore_container, args.ore_name, args.dry_run)
        rename_container(component_container, args.component_name, args.dry_run)
        if ingot_container:
            rename_container(ingot_container, args.ingot_name, args.dry_run)

        # Collect all inventories to process
        all_sources = grid.find_devices_containers()
        # Also include refinery, assembler, cockpit, etc. that might have items
        for d in grid.devices.values():
            if hasattr(d, 'get_inventory') and d not in all_sources:
                all_sources.append(d)

        # Debug: show all sources
        print(f"\nAll sources to process:")
        target_ids = {id(ore_container), id(component_container)}
        if ingot_container:
            target_ids.add(id(ingot_container))
        print(f"  Target IDs: {target_ids}")
        for s in all_sources:
            if hasattr(s, 'name'):
                is_target = id(s) in target_ids
                skip = " (TARGET - SKIP)" if is_target else ""
                if is_target:
                    print(f"  *** MATCH: {s.name} (id={id(s)})")
                else:
                    print(f"  - {s.name} (id={id(s)}){skip}")

        print(f"\n--- Moving items ---")
        total_moved = 0

        for source in all_sources:
            if id(source) in target_ids:
                continue
            if not hasattr(source, 'get_inventory'):
                continue

            source_inv = source.get_inventory()
            if not source_inv or not getattr(source_inv, 'items', None):
                continue

            has_ore = any(is_ore(item.type, item.subtype) for item in source_inv.items)
            has_component = any(is_component(item.type, item.subtype) for item in source_inv.items)
            has_ingot = any(is_ingot(item.type, item.subtype) for item in source_inv.items)

            if not (has_ore or has_component or has_ingot):
                continue

            print(f"\nProcessing {source.name}...")
            if has_ore:
                moved = move_items_between(source, ore_container, is_ore, args.dry_run)
                total_moved += moved
            if has_component:
                moved = move_items_between(source, component_container, is_component, args.dry_run)
                total_moved += moved
            if has_ingot and ingot_container:
                moved = move_items_between(source, ingot_container, is_ingot, args.dry_run)
                total_moved += moved

        print(f"\n=== Done! Total item stacks moved: {total_moved} ===")
        if args.dry_run:
            print("*** DRY RUN - no changes made ***")

    finally:
        close(grid)


if __name__ == "__main__":
    sys.exit(main())