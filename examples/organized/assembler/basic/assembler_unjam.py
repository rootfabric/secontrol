#!/usr/bin/env python3
"""Keep Space Engineers assemblers from being jammed by inventory clutter.

The script drains assembler output and optionally drains assembler input inventory
when it is clogged with items that are not needed by the current production
queue. It is intentionally conservative by default and can be run with --dry-run
first.

Typical usage:
    python examples/organized/assembler/basic/assembler_unjam.py --grid farpost0 --dry-run
    python examples/organized/assembler/basic/assembler_unjam.py --grid farpost0
    python examples/organized/assembler/basic/assembler_unjam.py --grid farpost0 --loop --interval 30
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root(Path(__file__).resolve())
SRC_PATH = REPO_ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

ENV_PATH = REPO_ROOT / ".env"
if ENV_PATH.exists():
    with ENV_PATH.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.inventory import InventoryItem, InventorySnapshot

EPSILON = 1e-6


@dataclass(frozen=True)
class TransferAction:
    assembler: AssemblerDevice
    source_inventory: InventorySnapshot
    destination: ContainerDevice
    destination_inventory: InventorySnapshot | None
    item: InventoryItem
    reason: str


def format_amount(value: float) -> str:
    value = float(value)
    rounded = round(value)
    if abs(value - rounded) <= EPSILON:
        return str(int(rounded))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def item_label(item: InventoryItem) -> str:
    display = item.display_name or item.subtype or "?"
    if item.type:
        return f"{display} [{item.type}/{item.subtype}]"
    return f"{display} [{item.subtype}]"


def item_payload(item: InventoryItem, amount: float | None = None) -> dict[str, Any]:
    return {
        "type": item.type,
        "subtype": item.subtype,
        "amount": float(item.amount if amount is None else amount),
    }


def subtype_key(value: Any) -> str:
    return str(value or "").strip().lower()


def blueprint_subtype(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def queue_entry_subtype(entry: dict[str, Any]) -> str:
    for key in ("blueprintSubtype", "subtype"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    for key in ("blueprintId", "blueprint", "id", "itemId"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    return ""


def refresh_device(device: Any, *, timeout: float = 0.8) -> None:
    try:
        device.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        try:
            device.update()
        except Exception:
            pass


def refresh_grid_devices(grid: Any) -> None:
    for device in grid.devices.values():
        if isinstance(device, (AssemblerDevice, ContainerDevice)):
            refresh_device(device, timeout=0.2)


def inventory_is_real(snapshot: InventorySnapshot | None) -> bool:
    return snapshot is not None and int(snapshot.index) >= 0


def get_device_name(device: Any) -> str:
    return str(getattr(device, "name", None) or getattr(device, "device_id", "unknown"))


def get_assemblers(grid: Any, *, name_filter: str | None = None) -> list[AssemblerDevice]:
    assemblers = [device for device in grid.devices.values() if isinstance(device, AssemblerDevice)]
    if name_filter:
        needle = name_filter.lower()
        assemblers = [asm for asm in assemblers if needle in get_device_name(asm).lower()]
    return sorted(assemblers, key=lambda asm: (get_device_name(asm).lower(), str(asm.device_id)))


def get_containers(
    grid: Any,
    *,
    destination_tag: str | None = None,
    destination_name: str | None = None,
    max_fill_ratio: float = 0.98,
) -> list[ContainerDevice]:
    containers: list[ContainerDevice] = []

    for device in grid.devices.values():
        if isinstance(device, AssemblerDevice):
            continue
        if not isinstance(device, ContainerDevice):
            continue

        if destination_name:
            if destination_name.lower() not in get_device_name(device).lower():
                continue

        if destination_tag:
            tags = getattr(device, "tags", set()) or set()
            if destination_tag.lower() not in {str(tag).lower() for tag in tags}:
                continue

        snapshot = device.inventory()
        if snapshot is None:
            continue
        if snapshot.max_volume > 0 and snapshot.fill_ratio >= max_fill_ratio:
            continue

        containers.append(device)

    def container_key(container: ContainerDevice) -> tuple[float, str, str]:
        snapshot = container.inventory()
        fill = snapshot.fill_ratio if snapshot else 1.0
        name = get_device_name(container).lower()
        return (float(fill), name, str(container.device_id))

    return sorted(containers, key=container_key)


def choose_destination(
    containers: list[ContainerDevice],
    *,
    item: InventoryItem,
    preferred_tags: Iterable[str],
) -> tuple[ContainerDevice | None, InventorySnapshot | None]:
    subtype = subtype_key(item.subtype)
    item_type = str(item.type or "").lower()

    tag_candidates = [tag.lower() for tag in preferred_tags if tag.strip()]

    if "ingot" in item_type or subtype in {"iron", "nickel", "cobalt", "silicon", "silver", "gold", "platinum", "uranium", "magnesium"}:
        tag_candidates = ["ingot", "ingots", "storage", "cargo", *tag_candidates]
    elif "component" in item_type:
        tag_candidates = ["component", "components", "storage", "cargo", *tag_candidates]
    elif "ore" in item_type:
        tag_candidates = ["ore", "storage", "cargo", *tag_candidates]
    else:
        tag_candidates = ["storage", "cargo", *tag_candidates]

    seen_tags: set[str] = set()
    ordered_tags: list[str] = []
    for tag in tag_candidates:
        if tag and tag not in seen_tags:
            seen_tags.add(tag)
            ordered_tags.append(tag)

    for tag in ordered_tags:
        for container in containers:
            tags = getattr(container, "tags", set()) or set()
            if tag not in {str(value).lower() for value in tags}:
                continue
            snapshot = container.inventory()
            if snapshot is not None:
                return container, snapshot

    for container in containers:
        snapshot = container.inventory()
        if snapshot is not None:
            return container, snapshot

    return None, None


def build_blueprint_index(assembler: AssemblerDevice) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    try:
        assembler.wait_for_blueprints(timeout=2.0)
    except Exception:
        pass

    for blueprint in assembler.blueprints or []:
        if not isinstance(blueprint, dict):
            continue
        blueprint_id = str(blueprint.get("blueprintId") or "").strip()
        bp_subtype = blueprint_subtype(blueprint_id)
        display_name = str(blueprint.get("displayName") or "").strip()

        for key in (blueprint_id, bp_subtype, display_name):
            normalized = subtype_key(blueprint_subtype(key) if "/" in str(key) else key)
            if normalized:
                index[normalized] = blueprint

        for result in blueprint.get("results", []) if isinstance(blueprint.get("results"), list) else []:
            if not isinstance(result, dict):
                continue
            result_subtype = subtype_key(result.get("subtype"))
            if result_subtype:
                index.setdefault(result_subtype, blueprint)

    return index


def required_input_subtypes(assembler: AssemblerDevice) -> set[str]:
    queue = assembler.queue()
    if not queue:
        return set()

    blueprints = build_blueprint_index(assembler)
    required: set[str] = set()

    for entry in queue:
        subtype = subtype_key(queue_entry_subtype(entry))
        if not subtype:
            continue

        blueprint = blueprints.get(subtype)
        if not blueprint:
            continue

        prereqs = blueprint.get("prerequisites", [])
        if not isinstance(prereqs, list):
            continue

        for prereq in prereqs:
            if not isinstance(prereq, dict):
                continue
            prereq_subtype = subtype_key(prereq.get("subtype"))
            if prereq_subtype:
                required.add(prereq_subtype)

    return required


def input_should_be_drained(
    assembler: AssemblerDevice,
    input_inventory: InventorySnapshot,
    item: InventoryItem,
    *,
    required_subtypes: set[str],
    keep_subtypes: set[str],
    force_input: bool,
    clogged_fill_ratio: float,
) -> tuple[bool, str]:
    item_subtype = subtype_key(item.subtype)
    if not item_subtype:
        return False, "item subtype is empty"

    if item_subtype in keep_subtypes:
        return False, "explicitly kept"

    if force_input:
        if required_subtypes and item_subtype in required_subtypes:
            return False, "needed by current queue"
        return True, "forced input cleanup"

    if required_subtypes:
        if item_subtype in required_subtypes:
            return False, "needed by current queue"
        return True, "not needed by current queue"

    if input_inventory.fill_ratio >= clogged_fill_ratio:
        return True, f"input is clogged: fillRatio={input_inventory.fill_ratio:.3f}"

    return False, "no blueprint prerequisites known and input is not clogged"


def collect_actions_for_assembler(
    assembler: AssemblerDevice,
    containers: list[ContainerDevice],
    *,
    drain_output: bool,
    drain_input: bool,
    force_input: bool,
    clogged_fill_ratio: float,
    keep_subtypes: set[str],
    preferred_tags: list[str],
) -> list[TransferAction]:
    actions: list[TransferAction] = []
    refresh_device(assembler, timeout=0.8)

    input_inventory = assembler.input_inventory()
    output_inventory = assembler.output_inventory()
    required_subtypes = required_input_subtypes(assembler) if drain_input else set()

    print(f"\nAssembler: {get_device_name(assembler)} ({assembler.device_id})")
    print(f"  queue items: {len(assembler.queue())}")
    if input_inventory:
        print(f"  input:  fill={input_inventory.fill_ratio:.3f}, items={len(input_inventory.items)}")
    else:
        print("  input:  unavailable")
    if output_inventory:
        print(f"  output: fill={output_inventory.fill_ratio:.3f}, items={len(output_inventory.items)}")
    else:
        print("  output: unavailable")

    if required_subtypes:
        print("  needed input subtypes from queue: " + ", ".join(sorted(required_subtypes)))
    elif drain_input:
        print("  needed input subtypes from queue: unknown or empty")

    if drain_output and inventory_is_real(output_inventory):
        for item in output_inventory.items:
            if item.amount <= EPSILON:
                continue
            destination, destination_inventory = choose_destination(containers, item=item, preferred_tags=preferred_tags)
            if destination is None:
                print(f"  [!] no destination for output item {item_label(item)}")
                continue
            actions.append(
                TransferAction(
                    assembler=assembler,
                    source_inventory=output_inventory,
                    destination=destination,
                    destination_inventory=destination_inventory,
                    item=item,
                    reason="assembler output cleanup",
                )
            )

    if drain_input and inventory_is_real(input_inventory):
        for item in input_inventory.items:
            if item.amount <= EPSILON:
                continue
            should_move, reason = input_should_be_drained(
                assembler,
                input_inventory,
                item,
                required_subtypes=required_subtypes,
                keep_subtypes=keep_subtypes,
                force_input=force_input,
                clogged_fill_ratio=clogged_fill_ratio,
            )
            if not should_move:
                print(f"  [keep] {format_amount(item.amount)} x {item_label(item)} — {reason}")
                continue
            destination, destination_inventory = choose_destination(containers, item=item, preferred_tags=preferred_tags)
            if destination is None:
                print(f"  [!] no destination for input item {item_label(item)}")
                continue
            actions.append(
                TransferAction(
                    assembler=assembler,
                    source_inventory=input_inventory,
                    destination=destination,
                    destination_inventory=destination_inventory,
                    item=item,
                    reason=reason,
                )
            )

    return actions


def apply_actions(actions: list[TransferAction], *, dry_run: bool, delay: float) -> int:
    sent_total = 0

    if not actions:
        print("\nNo cleanup actions required.")
        return 0

    print(f"\nPlanned transfers: {len(actions)}")

    for action in actions:
        print(
            "  "
            f"{get_device_name(action.assembler)}:{action.source_inventory.name} -> "
            f"{get_device_name(action.destination)} "
            f"{format_amount(action.item.amount)} x {item_label(action.item)} "
            f"({action.reason})"
        )

    if dry_run:
        print("\n[dry-run] No transfer commands were sent.")
        return 0

    print("\nSending transfer commands...")
    for action in actions:
        sent = action.assembler.move_items(
            action.destination,
            [item_payload(action.item)],
            source_inventory=action.source_inventory,
            destination_inventory=action.destination_inventory,
        )
        sent_total += int(sent or 0)
        print(
            "  [sent] "
            f"{get_device_name(action.assembler)} -> {get_device_name(action.destination)}: "
            f"{format_amount(action.item.amount)} x {item_label(action.item)}; messages={sent}"
        )
        if delay > 0:
            time.sleep(delay)

    print(f"\nTransfer commands sent: {sent_total}")
    return 0 if sent_total > 0 else 2


def run_once(args: argparse.Namespace) -> int:
    grid = prepare_grid(args.grid)
    try:
        refresh_grid_devices(grid)

        assemblers = get_assemblers(grid, name_filter=args.assembler_name)
        if not assemblers:
            print(f"No assemblers found on grid {args.grid}")
            return 1

        if not args.all_assemblers:
            assemblers = assemblers[:1]

        containers = get_containers(
            grid,
            destination_tag=args.destination_tag,
            destination_name=args.destination_name,
            max_fill_ratio=args.max_destination_fill,
        )
        if not containers:
            print("No suitable destination containers found.")
            print("Add a cargo container or lower --max-destination-fill.")
            return 1

        print(f"Grid: {grid.name}")
        print(f"Assemblers selected: {len(assemblers)}")
        print(f"Destination containers available: {len(containers)}")
        for container in containers[:5]:
            snapshot = container.inventory()
            fill = snapshot.fill_ratio if snapshot else 1.0
            print(f"  destination: {get_device_name(container)} ({container.device_id}), fill={fill:.3f}, tags={sorted(container.tags)}")

        keep_subtypes = {subtype_key(value) for value in args.keep_subtype}
        keep_subtypes.discard("")
        preferred_tags = [tag.strip().lower() for tag in args.preferred_tag if tag.strip()]

        all_actions: list[TransferAction] = []
        for assembler in assemblers:
            if args.enable_conveyor and not args.dry_run:
                try:
                    assembler.set_use_conveyor_verified(True, timeout=2.0)
                except Exception as exc:
                    print(f"  [!] cannot enable conveyor on {get_device_name(assembler)}: {exc}")
            actions = collect_actions_for_assembler(
                assembler,
                containers,
                drain_output=not args.no_output,
                drain_input=not args.no_input,
                force_input=args.force_input,
                clogged_fill_ratio=args.clogged_fill_ratio,
                keep_subtypes=keep_subtypes,
                preferred_tags=preferred_tags,
            )
            all_actions.extend(actions)

        return apply_actions(all_actions, dry_run=args.dry_run, delay=args.delay)
    finally:
        close(grid)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drain jammed assembler inventories into cargo containers")
    parser.add_argument("--grid", required=True, help="Grid name or ID")
    parser.add_argument("--assembler-name", help="Only process assemblers whose name contains this text")
    parser.add_argument("--all-assemblers", action="store_true", help="Process all assemblers instead of only the first one")
    parser.add_argument("--destination-tag", help="Only use containers with this tag, for example [ingot] or [cargo]")
    parser.add_argument("--destination-name", help="Only use destination containers whose name contains this text")
    parser.add_argument("--preferred-tag", action="append", default=[], help="Preferred destination tag; can be passed multiple times")
    parser.add_argument("--max-destination-fill", type=float, default=0.98, help="Skip destination containers whose fill ratio is above this value")
    parser.add_argument("--clogged-fill-ratio", type=float, default=0.85, help="Drain input inventory if no blueprint data is known and input fill ratio is at least this value")
    parser.add_argument("--keep-subtype", action="append", default=[], help="Never move this subtype from assembler input, for example Iron; can be repeated")
    parser.add_argument("--force-input", action="store_true", help="Drain assembler input even if it is not over the clogged threshold")
    parser.add_argument("--no-input", action="store_true", help="Do not clean assembler input inventory")
    parser.add_argument("--no-output", action="store_true", help="Do not clean assembler output inventory")
    parser.add_argument("--enable-conveyor", action="store_true", help="Enable Use Conveyor System on processed assemblers")
    parser.add_argument("--dry-run", action="store_true", help="Show planned transfers without sending commands")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=float, default=30.0, help="Loop interval in seconds")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between transfer commands")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.no_input and args.no_output:
        print("Both --no-input and --no-output are set; nothing to do.")
        raise SystemExit(1)

    while True:
        code = run_once(args)
        if not args.loop:
            raise SystemExit(code)
        print(f"\nSleeping {args.interval:.1f}s...\n")
        time.sleep(max(1.0, float(args.interval)))


if __name__ == "__main__":
    main()
