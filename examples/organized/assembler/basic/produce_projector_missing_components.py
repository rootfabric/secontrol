#!/usr/bin/env python3
"""Produce components required by projector missing blocks using all assemblers."""

from __future__ import annotations

import argparse
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
from secontrol.devices.projector_device import ProjectorDevice  # noqa: E402
from assembler_multi_common import (  # noqa: E402
    EPSILON,
    add_plan_to_assemblers,
    build_balanced_plan,
    component_to_blueprint_subtype,
    count_in_inventory,
    find_assemblers,
    find_item_type,
    format_amount,
    planned_queue_amounts_all,
    prepare_assemblers_for_build,
    print_assembler_state,
    refresh_assemblers,
)

SCRIPT_VERSION = "produce-projector-missing-components-v2-terminal-fallback-2026-06-04"


def find_projector(grid: Any, name_filter: str = "") -> ProjectorDevice | None:
    projectors = [p for p in grid.find_devices_by_type("projector") if isinstance(p, ProjectorDevice)]
    if name_filter:
        needle = name_filter.lower()
        projectors = [p for p in projectors if needle in str(p.name or "").lower()]
    return projectors[0] if projectors else None


def report_component_totals(report: dict[str, Any]) -> dict[str, float]:
    raw = report.get("componentTotals")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for name, value in raw.items():
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount > EPSILON:
            result[str(name)] = amount
    return result


def build_actions_from_components(
    grid: Any,
    components: dict[str, float],
    queue_amounts: dict[str, float],
    *,
    ignore_stock: bool = False,
) -> list[tuple[str, int]]:
    actions: list[tuple[str, int]] = []
    print("\nComponent demand:")
    for component_subtype, needed in sorted(components.items(), key=lambda item: (-item[1], item[0])):
        bp_subtype = component_to_blueprint_subtype(component_subtype)
        item_type = find_item_type(component_subtype)
        current = 0.0 if ignore_stock or item_type is None else count_in_inventory(grid, item_type)
        queued = queue_amounts.get(bp_subtype.lower(), 0.0)
        deficit = float(needed) - current - queued
        if deficit > EPSILON:
            amount = int(math.ceil(deficit - EPSILON))
            actions.append((bp_subtype, amount))
            status = f"add {amount}"
        else:
            status = "OK"
        print(
            f"  {component_subtype}: need {format_amount(needed)}, "
            f"stock {format_amount(current)}, queue {format_amount(queued)} -> {status}"
        )
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Produce components missing for current projector projection")
    parser.add_argument("--grid", required=True, help="Grid name or id")
    parser.add_argument("--projector-name", default="", help="Only use projector whose name contains this text")
    parser.add_argument("--assembler-name", default="", help="Only use assemblers whose name contains this text")
    parser.add_argument("--wait", type=float, default=3.0, help="Seconds to wait for projector report")
    parser.add_argument("--max-blocks", type=int, default=200, help="Max blocks returned in projector report")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without queue changes")
    parser.add_argument("--no-verify", action="store_true", help="Do not wait for queue telemetry confirmation")
    parser.add_argument("--verify-timeout", type=float, default=3.0, help="Telemetry confirmation timeout")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between queue commands")
    parser.add_argument("--ignore-stock", action="store_true", help="Produce full projector demand without subtracting current storage")
    parser.add_argument("--ignore-queue", action="store_true", help="Do not subtract existing assembler queue")
    parser.add_argument("--count-queue-in-disassemble-mode", action="store_true", help="Count queues even if assembler is in disassemble mode")
    args = parser.parse_args()

    print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
    grid = prepare_grid(args.grid, auto_wake=True)
    try:
        grid.refresh_devices()
        projector = find_projector(grid, args.projector_name)
        if projector is None:
            print("Projector not found")
            return 1

        report = projector.scan_projection_report(wait=args.wait, max_blocks=args.max_blocks)
        print(f"Grid: {grid.name} ({grid.grid_id})")
        print(f"Projector: {projector.name} ({projector.device_id})")
        if not report:
            print("projectionReport not returned. Обнови DedicatedPlugin до версии с projection_report.")
            return 2
        if not report.get("ready"):
            print(f"projectionReport not ready: {report.get('reason') or 'unknown reason'}")
            return 2

        source = report.get("source") or "cached_blueprint"
        print(
            f"Projected blocks: {report.get('projectedBlockCount')}, "
            f"built: {report.get('builtBlockCount')}, "
            f"missing: {report.get('missingBlockCount')}, incomplete: {report.get('incompleteBlockCount')}, "
            f"source: {source}"
        )
        if source == "projector_terminal_detailed_info":
            print("Внимание: компоненты рассчитаны fallback-методом из DetailedInfo проектора.")
            if report.get("componentTotalsComplete") is False:
                print("Внимание: часть типов блоков не сопоставлена с definition, очередь может покрывать не все компоненты.")
                unresolved = report.get("unresolvedTerminalBlocks")
                if isinstance(unresolved, list):
                    for item in unresolved[:20]:
                        if isinstance(item, dict):
                            print(f"  unresolved: {item.get('name')} x{item.get('count')}")
        components = report_component_totals(report)
        if not components:
            print("No components required by projector report.")
            return 0

        assemblers = find_assemblers(grid, name_filter=args.assembler_name, only_ready=True)
        refresh_assemblers(assemblers)
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
        actions = build_actions_from_components(grid, components, queue_amounts, ignore_stock=args.ignore_stock)
        if not actions:
            print("\nAll projector components are already covered by stock + queue.")
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

        print("\nProjector component production was distributed successfully.")
        return 0
    finally:
        close(grid)


if __name__ == "__main__":
    raise SystemExit(main())
