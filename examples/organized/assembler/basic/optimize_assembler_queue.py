#!/usr/bin/env python3
"""Redistribute existing assembler queue across all assemblers on a grid."""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
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
    build_balanced_plan,
    find_assemblers,
    format_amount,
    planned_queue_amounts_for_assembler,
    prepare_assemblers_for_build,
    print_assembler_state,
    refresh_assemblers,
)

SCRIPT_VERSION = "optimize-assembler-queue-v1-redistribute-all-assemblers-2026-06-04"


def collect_existing_queue(assemblers: list[Any], *, count_queue_in_disassemble_mode: bool) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for assembler in assemblers:
        items = planned_queue_amounts_for_assembler(
            assembler,
            ignore_queue=False,
            count_queue_in_disassemble_mode=count_queue_in_disassemble_mode,
        )
        if not items:
            continue
        print(f"Queue from {assembler.name}:")
        for subtype, amount in sorted(items.items()):
            print(f"  {subtype} x{format_amount(amount)}")
            totals[subtype] += amount
    return dict(totals)


def clear_queues(assemblers: list[Any], *, verify: bool, verify_timeout: float) -> bool:
    ok = True
    for assembler in assemblers:
        if verify:
            cleared = assembler.clear_queue_verified(timeout=verify_timeout)
        else:
            cleared = assembler.clear_queue() > 0
        print(f"  {assembler.name}: clear queue {'OK' if cleared else 'FAILED'}")
        ok = ok and bool(cleared)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Redistribute current assembler queue across all assemblers")
    parser.add_argument("--grid", required=True, help="Grid name or id")
    parser.add_argument("--assembler-name", default="", help="Only use assemblers whose name contains this text")
    parser.add_argument("--apply", action="store_true", help="Actually clear queues and apply redistributed plan")
    parser.add_argument("--no-verify", action="store_true", help="Do not wait for telemetry confirmation")
    parser.add_argument("--verify-timeout", type=float, default=3.0, help="Telemetry confirmation timeout")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between queue commands")
    parser.add_argument("--count-queue-in-disassemble-mode", action="store_true", help="Include queue from assemblers currently in disassemble mode")
    args = parser.parse_args()

    print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
    grid = prepare_grid(args.grid, auto_wake=True)
    try:
        grid.refresh_devices()
        assemblers = find_assemblers(grid, name_filter=args.assembler_name, only_ready=True)
        refresh_assemblers(assemblers)

        print(f"Grid: {grid.name} ({grid.grid_id})")
        print(f"Assemblers: {len(assemblers)}")
        for assembler in assemblers:
            print_assembler_state(assembler)
        if len(assemblers) < 2:
            print("Need at least two assemblers to redistribute queue.")
            return 1

        totals = collect_existing_queue(assemblers, count_queue_in_disassemble_mode=args.count_queue_in_disassemble_mode)
        if not totals:
            print("No known production queue found.")
            return 0

        actions = [(subtype, int(math.ceil(amount - EPSILON))) for subtype, amount in sorted(totals.items()) if amount > EPSILON]
        print("\nCollected total queue:")
        for subtype, amount in actions:
            print(f"  {subtype} x{amount}")

        plan = build_balanced_plan(assemblers, actions)
        print("\nRedistributed plan:")
        for assembler, bp_subtype, amount in plan:
            print(f"  {assembler.name}: {bp_subtype} x{amount}")

        if not args.apply:
            print("\n[dry-run] Add --apply to clear queues and apply this plan.")
            return 0

        print("\nPreparing assemblers for build mode...")
        prepare_assemblers_for_build(assemblers, verify=not args.no_verify, verify_timeout=args.verify_timeout)

        print("\nClearing old queues...")
        if not clear_queues(assemblers, verify=not args.no_verify, verify_timeout=args.verify_timeout):
            print("Queue clear failed; production plan was not applied.")
            return 2

        print("\nApplying redistributed queue...")
        failed = add_plan_to_assemblers(plan, verify=not args.no_verify, verify_timeout=args.verify_timeout, delay=args.delay)
        if failed:
            print("\nFailed to confirm queue additions:")
            for assembler_name, bp_subtype, amount in failed:
                print(f"  {assembler_name}: {bp_subtype} x{amount}")
            return 2

        print("\nQueue redistributed successfully.")
        return 0
    finally:
        close(grid)


if __name__ == "__main__":
    raise SystemExit(main())
