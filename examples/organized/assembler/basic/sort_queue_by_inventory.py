#!/usr/bin/env python3
"""Sort assembler queue: place scarce components first.

The script reorders the production queue of every assembler on a grid so that
blueprints whose components are scarce (low in inventory, not enough already
queued) move to the front. The rest of the queue is preserved in its original
relative order.

Scarcity rule (default, see --shortage-strategy):
    shortage = target - (inventory + sum_of_already_queued_across_all_assemblers)
    if (inventory + sum_of_already_queued_across_all_assemblers) < target:
        component is scarce
        amount_still_to_queue = max(1, target - (inventory + already_queued))

Targets default to `production_targets.json` (next to this file). Override with
--config <path>. Use --flat-target to apply a single number to every component.

The shortage is distributed across all assemblers on the grid so that the
combined amount of newly ordered items stays close to the total need (no
duplicates). A per-assembler minimum is `his_current_queue_amount`, because we
do not delete items that are already in his queue.

Typical usage:

    # Dry run, see the plan
    python examples/organized/assembler/basic/sort_queue_by_inventory.py --grid farpost0 --dry-run

    # Apply on the farpost base
    python examples/organized/assembler/basic/sort_queue_by_inventory.py --grid farpost0

    # Only one assembler
    python examples/organized/assembler/basic/sort_queue_by_inventory.py --grid farpost0 \\
        --assembler-name "Assembler 2" --dry-run

Important: reordering a Space Engineers assembler queue requires clearing and
re-adding the queue, because there is no stable insert-at-front command exposed
by the current wrapper. Always run --dry-run first. If the assembler has
`queueEnabled = false` in the SE terminal ("Use Production Queue" off), the
queue will not be processed until you toggle it manually in-game
(see `docs/agent-playbook/ASSEMBLER_QUEUE_ENABLED_LIMITATION.md`).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any


def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root(Path(__file__).resolve())
ENV_PATH = REPO_ROOT / ".env"
if ENV_PATH.exists():
    with ENV_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

# Put repo src first (for secontrol import) and the script directory second
# (for sibling modules: assembler_prioritize_needed, assembler_multi_common).
SRC_PATH = REPO_ROOT / "src"
if SRC_PATH.exists() and str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from secontrol.common import close, prepare_grid  # noqa: E402
from secontrol.devices.assembler_device import AssemblerDevice  # noqa: E402
from secontrol.item_types import COMPONENT_ITEMS, INGOT_ITEMS, item_matches  # noqa: E402

from assembler_multi_common import (  # noqa: E402
    BLUEPRINT_TO_INVENTORY,
    count_in_inventory,
    find_assemblers,
    format_amount,
    refresh_assemblers,
)
from assembler_prioritize_needed import (  # noqa: E402
    apply_queue_plan,
    blueprint_subtype,
    build_new_queue,
    print_current_queue,
)

SCRIPT_VERSION = "sort-queue-by-inventory-v1-2026-06-09"
EPSILON = 1e-6
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "production_targets.json"


def load_targets(config_path: Path | None) -> dict[str, int]:
    if config_path is None or not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config must be an object: {config_path}")
    targets: dict[str, int] = {}
    for key, value in data.items():
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if amount < 0:
            continue
        targets[str(key)] = amount
    return targets


def find_item_type(inventory_subtype: str):
    for item in COMPONENT_ITEMS:
        if item.subtype == inventory_subtype:
            return item
    for item in INGOT_ITEMS:
        if item.subtype == inventory_subtype:
            return item
    return None


def blueprint_to_inventory_subtype(component_subtype: str) -> str:
    return BLUEPRINT_TO_INVENTORY.get(component_subtype, component_subtype)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def queue_amounts_for_assembler(assembler: AssemblerDevice) -> dict[str, float]:
    """Return inventory-subtype -> amount for the assembler's production queue.

    Note: queue entries use the BLUEPRINT subtype (e.g. ``ComputerComponent``)
    while the inventory API uses the component subtype (``Computer``). We map
    every entry through ``BLUEPRINT_TO_INVENTORY`` so totals line up with
    inventory totals and with ``compute_global_shortage`` keys.
    """
    totals: defaultdict[str, float] = defaultdict(float)
    telemetry = assembler.telemetry or {}
    if bool(telemetry.get("disassembleEnabled", False)):
        return {}
    for entry in assembler.queue():
        blueprint_sub = queue_entry_subtype(entry)
        if not blueprint_sub:
            continue
        inv_subtype = blueprint_to_inventory_subtype(blueprint_sub).lower()
        amount = safe_float(entry.get("amount"), 0.0)
        if amount > EPSILON:
            totals[inv_subtype] += amount
    return dict(totals)


def collect_inventory(grid: Any) -> dict[str, float]:
    inventory: dict[str, float] = {}
    for item in COMPONENT_ITEMS:
        inventory[item.subtype] = count_in_inventory(grid, item)
    return inventory


def compute_global_shortage(
    inventory: dict[str, float],
    total_queued: dict[str, float],
    targets: dict[str, int],
) -> "OrderedDict[str, tuple[float, float]]":
    """Return OrderedDict[component] = (target, amount_still_to_queue).

    amount_still_to_queue is what must still be added to the queues across the
    grid so that inventory + queued reaches the target. The caller splits this
    across assemblers.
    """
    shortage: OrderedDict[str, tuple[float, float]] = OrderedDict()
    for component, target in targets.items():
        inv_subtype = blueprint_to_inventory_subtype(component)
        inv_amount = float(inventory.get(inv_subtype, 0.0))
        queued_amount = float(total_queued.get(inv_subtype.lower(), 0.0))
        planned = inv_amount + queued_amount
        if planned < float(target):
            still_needed = max(1.0, float(target) - planned)
            shortage[component] = (float(target), still_needed)
    return shortage


def distribute_shortage_per_assembler(
    shortage_total: dict[str, float],
    queue_per_assembler: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """For each assembler, compute the per-component amount he should have in
    his queue so the combined total across assemblers matches `shortage_total`
    as closely as possible without dropping below his current queue amount.

    Result is rounded up to whole units since the SE queue does not accept
    fractional amounts.
    """
    per_assembler: dict[str, dict[str, float]] = {}
    assembler_ids = list(queue_per_assembler.keys())

    for component, total_need in shortage_total.items():
        inv_subtype = blueprint_to_inventory_subtype(component)
        per_a_need: dict[str, float] = {}
        for a_id in assembler_ids:
            current = queue_per_assembler.get(a_id, {}).get(inv_subtype.lower(), 0.0)
            per_a_need[a_id] = max(0.0, total_need - current)

        scale_sum = sum(per_a_need.values())
        if scale_sum > total_need and scale_sum > EPSILON:
            factor = total_need / scale_sum
            for a_id in per_a_need:
                per_a_need[a_id] *= factor

        for a_id in assembler_ids:
            bucket = per_assembler.setdefault(a_id, {})
            amount = per_a_need[a_id]
            if amount > EPSILON:
                bucket[component] = float(math.ceil(amount - EPSILON))

    return per_assembler


def refresh_assembler_fully(assembler: AssemblerDevice, *, timeout: float = 1.0) -> None:
    try:
        assembler.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        try:
            assembler.update()
        except Exception:
            pass
    try:
        assembler.wait_for_blueprints(timeout=2.0)
    except Exception:
        pass


def warn_if_queue_disabled(assembler: AssemblerDevice) -> None:
    telemetry = assembler.telemetry or {}
    if "queueEnabled" in telemetry and not bool(telemetry.get("queueEnabled")):
        print(
            f"  [!] {assembler.name}: queueEnabled=false в телеметрии. "
            f"Очередь не будет обрабатываться, пока не включишь "
            f"'Use Production Queue' в терминале блока вручную."
        )


def process_assembler(
    assembler: AssemblerDevice,
    needed: "OrderedDict[str, float]",
    *,
    dry_run: bool,
    verify_timeout: float,
    delay: float,
) -> int:
    print(f"\n--- Assembler: {assembler.name} ({assembler.device_id}) ---")
    telemetry = assembler.telemetry or {}
    print(
        f"  mode={assembler.mode() or 'unknown'} "
        f"disassemble={bool(telemetry.get('disassembleEnabled', False))} "
        f"queue_items={len(assembler.queue())} "
        f"producing={bool(telemetry.get('isProducing', False))}"
    )
    warn_if_queue_disabled(assembler)

    if not needed:
        print("  Нет дефицитных компонентов — очередь не трогаем.")
        return 0

    print("  Нужно дозаказать (на этот ассемблер):")
    for component, amount in needed.items():
        print(f"    - {component} x{format_amount(amount)}")

    current_queue = assembler.queue()
    print_current_queue(current_queue)

    plan = build_new_queue(current_queue, needed, add_missing=True)
    if not plan:
        print("  План пуст — ничего не меняем.")
        return 0

    print("  План новой очереди:")
    for i, (blueprint, amount, reason) in enumerate(plan, start=1):
        print(f"    [{i}] {blueprint_subtype(blueprint)} x{format_amount(amount)} — {reason}")

    if dry_run:
        print("  [dry-run] Очередь не изменена. Убери --dry-run для применения.")
        return 0

    code = apply_queue_plan(
        assembler,
        plan,
        verify_timeout=verify_timeout,
        delay=delay,
        set_assemble_mode=True,
    )
    if code == 0:
        refresh_assembler_fully(assembler, timeout=1.0)
        print("  Итоговая очередь:")
        print_current_queue(assembler.queue())
    return code


def parse_assembler_targets(
    args_targets: list[str],
    file_targets: dict[str, int],
    flat_target: int | None,
) -> dict[str, int]:
    merged: dict[str, int] = {}
    if file_targets:
        merged.update(file_targets)
    for raw in args_targets:
        if "=" not in raw:
            raise ValueError(f"--target expects Component=Amount, got {raw!r}")
        name, amount = raw.split("=", 1)
        name = name.strip()
        if not name:
            continue
        try:
            qty = int(float(amount))
        except (TypeError, ValueError):
            raise ValueError(f"--target: invalid amount for {name!r}: {amount!r}")
        if qty < 0:
            continue
        merged[name] = qty
    if flat_target is not None:
        for component in list(merged.keys()):
            merged[component] = flat_target
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sort assembler queue so scarce components come first",
    )
    parser.add_argument("--grid", required=True, help="Grid name or ID")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to JSON with target amounts per component (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Override/add target as Component=Amount (can be repeated)",
    )
    parser.add_argument(
        "--flat-target",
        type=int,
        default=None,
        help="Apply a single target amount to every component in --config/--target",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="Ignore the default production_targets.json; only --target entries are used",
    )
    parser.add_argument(
        "--assembler-name",
        default="",
        help="Substring filter — only process assemblers whose name contains this. NOTE: queues of excluded assemblers are NOT credited toward shortage.",
    )
    parser.add_argument(
        "--assembler-id",
        default="",
        help="Process a single assembler by exact device ID. NOTE: queues of excluded assemblers are NOT credited toward shortage.",
    )
    parser.add_argument(
        "--include-subgrids",
        action="store_true",
        help="Include assemblers on attached subgrids (off by default)",
    )
    parser.add_argument(
        "--shortage-strategy",
        choices=["inventory_and_queue"],
        default="inventory_and_queue",
        help=(
            "How to decide that a component is scarce. "
            "Default: 'inventory_and_queue' — component is scarce if "
            "inventory + sum_of_already_queued_across_all_assemblers < target."
        ),
    )
    parser.add_argument(
        "--ignore-queue",
        action="store_true",
        help="Do not credit already-queued amounts when computing shortage",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the new queue plan without changing any queue",
    )
    parser.add_argument(
        "--verify-timeout",
        type=float,
        default=3.0,
        help="Seconds to wait for each queue command confirmation",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay between queue commands",
    )
    args = parser.parse_args()

    print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
    print(f"Grid: {args.grid}")
    print(f"Shortage strategy: {args.shortage_strategy}")

    config_path = None if args.no_config else args.config
    file_targets = load_targets(config_path) if config_path else {}
    if config_path is not None:
        print(f"Config: {config_path} ({len(file_targets)} component targets)")

    try:
        targets = parse_assembler_targets(args.target, file_targets, args.flat_target)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    if not targets:
        print(
            "ERROR: no targets defined. Provide --config, --target Component=N, "
            "or both."
        )
        return 2

    print("Targets:")
    for component, amount in sorted(targets.items()):
        print(f"  - {component} = {amount}")

    grid = prepare_grid(args.grid, auto_wake=True)
    try:
        grid.refresh_devices()
        assemblers = find_assemblers(
            grid,
            name_filter=args.assembler_name,
            only_ready=False,
            include_subgrids=args.include_subgrids,
        )
        if args.assembler_id:
            wanted = args.assembler_id.strip()
            assemblers = [a for a in assemblers if str(a.device_id) == wanted]
            if not assemblers:
                print(f"ERROR: no assembler matched --assembler-id {wanted}")
                return 1

        if not assemblers:
            print("ERROR: no assembler matched selection")
            return 1

        refresh_assemblers(assemblers, timeout=1.0)
        for a in assemblers:
            try:
                a.wait_for_blueprints(timeout=2.0)
            except Exception:
                pass

        print(f"\nAssemblers to process: {len(assemblers)}")
        for a in assemblers:
            telemetry = a.telemetry or {}
            print(
                f"  {a.name} ({a.device_id}) "
                f"mode={a.mode() or 'unknown'} "
                f"queue={len(a.queue())} "
                f"producing={bool(telemetry.get('isProducing', False))}"
            )

        # Суммируем очереди выбранных ассемблеров по subtype.
        # Внимание: если указан --assembler-name/--assembler-id, мы НЕ
        # учитываем очереди ассемблеров вне выборки. Это значит, что
        # shortage может быть переоценён, если на других ассемблерах уже
        # заказано много нужного. Чтобы учесть всё — запускайте без фильтра.
        queue_per_assembler: dict[str, dict[str, float]] = {}
        total_queued: dict[str, float] = defaultdict(float)
        for a in assemblers:
            q = queue_amounts_for_assembler(a)
            queue_per_assembler[a.device_id] = q
            for subtype, amount in q.items():
                total_queued[subtype] += amount

        if args.ignore_queue:
            total_queued = defaultdict(float)
            for a in assemblers:
                queue_per_assembler[a.device_id] = {}

        # Inventory грида (компоненты).
        inventory = collect_inventory(grid)
        print("\nInventory components (across all containers):")
        for component, amount in sorted(inventory.items()):
            if amount > EPSILON:
                print(f"  - {component} = {format_amount(amount)}")

        shortage_pairs = compute_global_shortage(inventory, dict(total_queued), targets)
        if not shortage_pairs:
            print("\nДефицита нет — все цели достигнуты (inventory + queue ≥ target).")
            return 0

        shortage_total = OrderedDict(
            (component, to_order) for component, (_, to_order) in shortage_pairs.items()
        )
        print("\nGlobal shortage (sum across all assemblers):")
        for component, (target, to_order) in shortage_pairs.items():
            inv_subtype = blueprint_to_inventory_subtype(component)
            inv_amount = float(inventory.get(inv_subtype, 0.0))
            already_queued = float(total_queued.get(inv_subtype.lower(), 0.0))
            print(
                f"  - {component}: target={format_amount(target)}, "
                f"inventory={format_amount(inv_amount)}, "
                f"already_queued={format_amount(already_queued)}, "
                f"need_to_order={format_amount(to_order)}"
            )

        per_assembler = distribute_shortage_per_assembler(
            shortage_total, queue_per_assembler
        )

        # Если --assembler-id указан, обрабатываем один; иначе все.
        exit_code = 0
        for a in assemblers:
            needed = OrderedDict(per_assembler.get(a.device_id, {}))
            rc = process_assembler(
                a,
                needed,
                dry_run=args.dry_run,
                verify_timeout=args.verify_timeout,
                delay=args.delay,
            )
            if rc != 0:
                exit_code = rc
        return exit_code
    finally:
        close(grid)


if __name__ == "__main__":
    raise SystemExit(main())
