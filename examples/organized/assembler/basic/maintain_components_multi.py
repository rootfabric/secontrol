#!/usr/bin/env python3
"""Maintain component stock using all assemblers on the grid."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


def add_local_src_to_path() -> None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "src"
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            return


add_local_src_to_path()

from secontrol.common import close, prepare_grid  # noqa: E402
from assembler_multi_common import (  # noqa: E402
    EPSILON,
    add_plan_to_assemblers,
    blueprint_to_inventory_subtype,
    build_balanced_plan,
    count_in_inventory,
    find_assemblers,
    find_item_type,
    format_amount,
    planned_queue_amounts_all,
    prepare_assemblers_for_build,
    print_assembler_state,
    refresh_assemblers,
)

SCRIPT_VERSION = "maintain-components-multi-v1-balanced-all-assemblers-2026-06-04"
CONFIG_PATH = Path(__file__).parent / "production_targets.json"


def load_targets(config_path: Path) -> dict[str, int]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config must contain an object: {config_path}")
    result: dict[str, int] = {}
    for key, value in data.items():
        amount = int(value)
        if amount < 0:
            raise ValueError(f"Target amount must be >= 0 for {key}: {amount}")
        result[str(key)] = amount
    return result


def build_actions_from_targets(
    grid: Any,
    targets: dict[str, int],
    queue_amounts: dict[str, float],
) -> list[tuple[str, int]]:
    actions: list[tuple[str, int]] = []
    print("=" * 80)
    print(f"Targets: {len(targets)}")
    for bp_subtype, target_amount in targets.items():
        inv_subtype = blueprint_to_inventory_subtype(bp_subtype)
        item_type = find_item_type(inv_subtype)
        if not item_type:
            print(f"[!] {bp_subtype}: unknown inventory component subtype '{inv_subtype}', skipped")
            continue

        current = count_in_inventory(grid, item_type)
        queued = queue_amounts.get(bp_subtype.lower(), 0.0)
        planned_total = current + queued
        deficit = float(target_amount) - planned_total
        if deficit > EPSILON:
            amount = int(math.ceil(deficit - EPSILON))
            actions.append((bp_subtype, amount))
            status = f"add {amount}"
        else:
            status = "OK"

        print(
            f"  {item_type.display_name}: stock {format_amount(current)} + queue {format_amount(queued)} "
            f"= {format_amount(planned_total)}/{target_amount} — {status}"
        )
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain component stock with all assemblers")
    parser.add_argument("--grid", required=True, help="Grid name or id")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to production target JSON")
    parser.add_argument("--assembler-name", default="", help="Only use assemblers whose name contains this text")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without queue changes")
    parser.add_argument("--no-verify", action="store_true", help="Do not wait for telemetry confirmation")
    parser.add_argument("--verify-timeout", type=float, default=3.0, help="Telemetry confirmation timeout")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between queue commands")
    parser.add_argument("--ignore-queue", action="store_true", help="Do not count existing assembler queues")
    parser.add_argument("--count-queue-in-disassemble-mode", action="store_true", help="Count queues even if assembler is currently in disassemble mode")
    args = parser.parse_args()

    print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    try:
        targets = load_targets(config_path)
    except Exception as exc:
        print(f"Failed to read config: {exc}")
        return 1

    grid = prepare_grid(args.grid, auto_wake=True)
    try:
        grid.refresh_devices()
        assemblers = find_assemblers(grid, name_filter=args.assembler_name, only_ready=True)
        refresh_assemblers(assemblers)

        print(f"Grid: {grid.name} ({grid.grid_id})")
        print(f"Assemblers used: {len(assemblers)}")
        for assembler in assemblers:
            print_assembler_state(assembler)
        if not assemblers:
            return 1

        queue_amounts = planned_queue_amounts_all(
            assemblers,
            ignore_queue=args.ignore_queue,
            count_queue_in_disassemble_mode=args.count_queue_in_disassemble_mode,
        )
        print(f"Known queued production: {format_amount(sum(queue_amounts.values()))} items")

        actions = build_actions_from_targets(grid, targets, queue_amounts)
        if not actions:
            print("\nEverything is already covered by stock + existing queues.")
            return 0

        print("\nProduction needed:")
        for bp_subtype, amount in actions:
            print(f"  {bp_subtype} x{amount}")

        plan = build_balanced_plan(assemblers, actions)
        print("\nBalanced queue plan:")
        for assembler, bp_subtype, amount in plan:
            print(f"  {assembler.name}: {bp_subtype} x{amount}")

        if args.dry_run:
            print("\n[dry-run] Queue was not changed.")
            return 0

        print("\nPreparing assemblers for build mode...")
        prepare_assemblers_for_build(assemblers, verify=not args.no_verify, verify_timeout=args.verify_timeout)
        failed = add_plan_to_assemblers(plan, verify=not args.no_verify, verify_timeout=args.verify_timeout, delay=args.delay)
        if failed:
            print("\nFailed to confirm queue additions:")
            for assembler_name, bp_subtype, amount in failed:
                print(f"  {assembler_name}: {bp_subtype} x{amount}")
            return 2

        print("\nProduction queue distributed successfully.")
        return 0
    finally:
        close(grid)


if __name__ == "__main__":
    raise SystemExit(main())
