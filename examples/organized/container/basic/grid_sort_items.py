#!/usr/bin/env python3
"""One-shot sorter: sort every item on a grid into 4 dedicated containers.

Required destination containers (one per category):
  1. ore       - all items with type MyObjectBuilder_Ore
  2. component - all items with type MyObjectBuilder_Component
  3. ingot     - all items with type MyObjectBuilder_Ingot
  4. misc      - everything else (tools, ammo, gas bottles, datapads, ...)

How the script picks each destination container (first match wins):
  1. CLI override by name (substring, e.g. --ore-name "[Ore Storage]").
  2. Tag on the block: square brackets in the name (`[Ore]`, `[Component]` ...)
     or `tags: ...` lines in the block's custom data.
     Tags are matched case-insensitively against `ore|component|ingot|misc`.

The script refuses to run if any of the 4 destinations cannot be resolved,
so a misconfigured grid fails loudly instead of silently dropping items.

Source containers (everything iterated to find items to move):
  - Cargo containers, cockpits, connectors, ship drills/grinders:
    every item in their single inventory is moved.
  - Refineries and assemblers: only the OUTPUT inventory is touched.
    Their input inventory is left alone, so refining/production recipes
    in progress are not disturbed.
  - Conveyor sorters, reactors, and all turrets (large/interior) are
    SKIPPED entirely:
      * conveyor sorters store filter slots, not real items;
      * turrets keep their loaded ammo/missiles (operator manages loads);
      * reactor uranium fuel stays in the reactor input.

Usage:
    python examples/organized/container/grid_sort_items.py --grid farpost0
    python examples/organized/container/grid_sort_items.py --grid farpost0 --dry-run
    python examples/organized/container/grid_sort_items.py --grid farpost0 \\
        --ore-name "[Ore]" --component-name "[Component]" \\
        --ingot-name "[Ingot]" --misc-name "[Misc]"

After sending all transfer commands the script waits a few seconds and
re-reads the four destination inventories (observe -> command -> verify).
A final per-category summary is printed so the operator can confirm that
items actually arrived and not just that the command was published.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice
from secontrol.inventory import InventoryItem, InventorySnapshot
from secontrol.item_types import is_component, is_ingot, is_ore


CATEGORY_ORE = "ore"
CATEGORY_COMPONENT = "component"
CATEGORY_INGOT = "ingot"
CATEGORY_MISC = "misc"

REQUIRED_CATEGORIES: Tuple[str, ...] = (
    CATEGORY_ORE,
    CATEGORY_COMPONENT,
    CATEGORY_INGOT,
    CATEGORY_MISC,
)

# Device types that have separate input + output inventories.
# We only touch the output of these — input is left for production logic.
PRODUCTION_DEVICES_WITH_INPUT: Set[str] = {"assembler", "refinery"}

# Device types that are not real "storage" and should be skipped entirely.
#   - conveyor_sorter: filter slots, not storage.
#   - large_turret / interior_turret: turrets keep their loaded ammo/missiles
#     in place; the operator manages turret loads manually.
#   - reactor: uranium fuel is reactor input, never a movable item. The
#     reactor has no output inventory, so PRODUCTION_DEVICES_WITH_INPUT
#     already skips it; we also list it here for safety and to make the
#     intent obvious when reading the source list.
SKIP_DEVICE_TYPES: Set[str] = {
    "conveyor_sorter",
    "large_turret",
    "interior_turret",
    "reactor",
}


# ---------------------------------------------------------------------------
# Item classification
# ---------------------------------------------------------------------------
def classify(item: InventoryItem) -> str:
    """Map an inventory item to one of the 4 required categories."""
    if is_ore(item):
        return CATEGORY_ORE
    if is_ingot(item):
        return CATEGORY_INGOT
    if is_component(item):
        return CATEGORY_COMPONENT
    return CATEGORY_MISC


# ---------------------------------------------------------------------------
# Destination container resolution
# ---------------------------------------------------------------------------
def _match_by_name(container: ContainerDevice, name_substring: str) -> bool:
    if not container.name or not name_substring:
        return False
    return name_substring.lower().strip() in container.name.lower()


def find_destination(
    grid,
    category: str,
    override_name: Optional[str],
) -> Tuple[Optional[ContainerDevice], bool]:
    """Find the destination container for ``category``.

    Returns ``(container, override_used)`` where ``override_used`` is True
    when the match came from the explicit CLI override.
    """
    containers = [
        c for c in grid.find_devices_containers() if isinstance(c, ContainerDevice)
    ]

    if override_name:
        for c in containers:
            if _match_by_name(c, override_name):
                return c, True
        print(
            f"  [WARN] --{category}-name='{override_name}' did not match any container; falling back to tag detection",
            file=sys.stderr,
        )

    for c in containers:
        if c.has_tag(category):
            return c, False

    return None, False


def resolve_destinations(
    grid,
    overrides: Dict[str, Optional[str]],
) -> Dict[str, ContainerDevice]:
    """Resolve all 4 destination containers or fail loudly."""
    print("\n--- Destination containers ---")
    found: Dict[str, ContainerDevice] = {}
    missing: List[str] = []
    for category in REQUIRED_CATEGORIES:
        dest, override_used = find_destination(grid, category, overrides.get(category))
        if dest is None:
            missing.append(category)
            print(f"  [{category:9s}] MISSING")
            continue
        if dest.device_id in {d.device_id for d in found.values()}:
            raise SystemExit(
                f"ERROR: container '{dest.name}' is already used as a destination for another category. "
                f"Each of ore/component/ingot/misc must map to a distinct container."
            )
        origin = "override" if override_used else ("tag" if dest.tags else "fallback")
        tags = f"  tags={sorted(dest.tags)}" if dest.tags else ""
        print(f"  [{category:9s}] {dest.name} (id={dest.device_id})  [{origin}]{tags}")
        found[category] = dest

    if missing:
        names = ", ".join(missing)
        print(
            "\nERROR: not enough destination containers. Missing: "
            f"{names}.\n"
            "Tag one container per category, e.g.:\n"
            "  - rename to '[Ore]', '[Component]', '[Ingot]', '[Misc]'\n"
            "  - or set custom data: 'tags: ore' / 'tags: component' / 'tags: ingot' / 'tags: misc'\n"
            "  - or use --ore-name/--component-name/--ingot-name/--misc-name CLI flags.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return found


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------
def _iter_source_inventories(device) -> List[Tuple[str, Optional[InventorySnapshot]]]:
    """Return the list of (label, snapshot) inventories to process for a source device.

    - Production devices (assembler/refinery) yield only the output inventory.
    - Other devices yield their single inventory (or all inventories if multiple).
    """
    if device.device_type in PRODUCTION_DEVICES_WITH_INPUT:
        output = device.output_inventory()
        return [("output", output)] if output else []

    inv = device.get_inventory()
    if inv is None:
        return []
    return [("", inv)]


# ---------------------------------------------------------------------------
# Move loop
# ---------------------------------------------------------------------------
def _send_move(
    source,
    destination: ContainerDevice,
    subtype: str,
    *,
    source_inventory: Optional[InventorySnapshot],
    dry_run: bool,
) -> bool:
    if dry_run:
        return True
    try:
        source.move_subtype(
            destination,
            subtype,
            source_inventory=source_inventory,
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive guard for runtime errors
        print(f"    [ERROR] move_subtype {subtype}: {exc}")
        return False


def move_from_source(
    source,
    destinations: Dict[str, ContainerDevice],
    *,
    dry_run: bool,
) -> int:
    """Move every sortable item from ``source`` to the right category container.

    Returns the number of transfer commands successfully sent.
    """
    moved = 0
    inventories = _iter_source_inventories(source)
    if not inventories:
        return 0

    for label, inv in inventories:
        if not inv or not inv.items:
            continue
        suffix = f" [{label}]" if label else ""
        print(f"\n  -> {source.name} ({source.device_type}){suffix}")
        for item in list(inv.items):
            category = classify(item)
            dest = destinations[category]
            display = item.display_name or item.subtype or "?"
            amount = (
                int(item.amount)
                if item.amount == int(item.amount)
                else round(item.amount, 2)
            )
            print(f"     {display} x{amount}  ->  [{category}] {dest.name}")
            if _send_move(
                source,
                dest,
                item.subtype,
                source_inventory=inv,
                dry_run=dry_run,
            ):
                moved += 1
    return moved


# ---------------------------------------------------------------------------
# Verify (observe -> command -> verify)
# ---------------------------------------------------------------------------
def verify_sort(
    grid,
    destinations: Dict[str, ContainerDevice],
    *,
    settle_seconds: float,
) -> None:
    """Re-read destination inventories after a delay and print a summary."""
    if settle_seconds > 0:
        print(f"\nWaiting {settle_seconds:.1f}s for the server to apply transfers...")
        time.sleep(settle_seconds)
    print("\n--- Verification (re-read) ---")
    for category in REQUIRED_CATEGORIES:
        dest = destinations[category]
        items = dest.inventory_items() or []
        total = sum(i.amount for i in items)
        total_str = int(total) if total == int(total) else round(total, 2)
        print(
            f"  [{category:9s}] {dest.name}: {len(items)} stack(s), amount={total_str}"
        )
        for item in sorted(items, key=lambda i: -i.amount):
            amount = (
                int(item.amount)
                if item.amount == int(item.amount)
                else round(item.amount, 2)
            )
            print(f"      - {item.display_name or item.subtype or '?'}: {amount}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _iter_sources(grid, destination_ids: Set[int]):
    """Yield every container that is NOT a destination and is not skipped."""
    for device in grid.find_devices_containers():
        if not isinstance(device, ContainerDevice):
            continue
        if device.device_id in destination_ids:
            continue
        if device.device_type in SKIP_DEVICE_TYPES:
            continue
        yield device


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sort every item on a grid into 4 dedicated containers (ore/component/ingot/misc).",
    )
    parser.add_argument("--grid", required=True, help="Grid name or ID to sort")
    parser.add_argument(
        "--ore-name", default=None, help="Override ore container name (substring match)"
    )
    parser.add_argument(
        "--component-name",
        default=None,
        help="Override component container name (substring match)",
    )
    parser.add_argument(
        "--ingot-name",
        default=None,
        help="Override ingot container name (substring match)",
    )
    parser.add_argument(
        "--misc-name",
        default=None,
        help="Override misc container name (substring match)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be moved without sending commands",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the post-sort verification re-read",
    )
    parser.add_argument(
        "--verify-delay",
        type=float,
        default=2.0,
        help="Seconds to wait before verification re-read (default: 2.0)",
    )
    args = parser.parse_args()

    print(f"=== Sort items on grid '{args.grid}' ===")
    if args.dry_run:
        print("*** DRY RUN: no transfer commands will be sent ***")

    grid = prepare_grid(args.grid)
    try:
        # 1) Resolve the 4 destination containers (or fail loudly).
        overrides = {
            CATEGORY_ORE: args.ore_name,
            CATEGORY_COMPONENT: args.component_name,
            CATEGORY_INGOT: args.ingot_name,
            CATEGORY_MISC: args.misc_name,
        }
        destinations = resolve_destinations(grid, overrides)
        destination_ids = {c.device_id for c in destinations.values()}

        # 2) Discover all source containers.
        sources = list(_iter_sources(grid, destination_ids))
        print(f"\n--- Sources: {len(sources)} container(s) to process ---")
        for s in sources:
            print(f"  - {s.name} ({s.device_type})")
        if not sources:
            print("  (none)")

        # 3) Move items.
        total = 0
        for source in sources:
            total += move_from_source(source, destinations, dry_run=args.dry_run)

        print(f"\n=== Done. Transfer commands sent: {total} ===")

        # 4) Verify (observe -> command -> verify).
        if not args.dry_run and not args.no_verify:
            verify_sort(grid, destinations, settle_seconds=args.verify_delay)
        elif args.dry_run:
            print("(skipped verification in dry-run mode)")
        else:
            print("(verification skipped via --no-verify)")

        return 0
    finally:
        close(grid)


if __name__ == "__main__":
    sys.exit(main())
