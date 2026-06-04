#!/usr/bin/env python3
"""Show missing projected blocks and required construction components."""

from __future__ import annotations

import argparse
import json
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

SCRIPT_VERSION = "projector-missing-components-v2-terminal-fallback-2026-06-04"


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def amount_text(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-6:
        return str(int(round(number)))
    return f"{number:.3f}".rstrip("0").rstrip(".")


def sorted_amount_items(data: Any) -> list[tuple[str, Any]]:
    if not isinstance(data, dict):
        return []
    return sorted(data.items(), key=lambda item: (-float(item[1] or 0), item[0]))


def find_projectors(grid: Any, name_filter: str = "") -> list[ProjectorDevice]:
    projectors = [p for p in grid.find_devices_by_type("projector") if isinstance(p, ProjectorDevice)]
    if name_filter:
        needle = name_filter.lower()
        projectors = [p for p in projectors if needle in str(p.name or "").lower()]
    return projectors


def print_projector_report(projector: ProjectorDevice, report: dict[str, Any], *, full: bool = False) -> None:
    telemetry = projector.telemetry or {}
    print("-" * 100)
    print(f"Projector: {projector.name} ({projector.device_id})")
    print(
        "telemetry: "
        f"enabled={telemetry.get('enabled')} "
        f"projecting={telemetry.get('isProjecting')} "
        f"remaining={telemetry.get('remainingBlocks')} "
        f"buildable={telemetry.get('buildableBlocks')} "
        f"total={telemetry.get('totalBlocks')}"
    )

    if not report:
        print("projectionReport: not returned. Обнови DedicatedPlugin до версии с командой projection_report.")
        return

    if not report.get("ready"):
        print(f"projectionReport: not ready: {report.get('reason') or 'unknown reason'}")
        print("Подсказка: если нужен точный список блоков и компонентов, загрузи проекцию через plugin load_blueprint_xml/load_prefab.")
        return

    source = report.get("source") or "cached_blueprint"
    print(
        "report: "
        f"source={source} "
        f"projected={report.get('projectedBlockCount')} "
        f"built={report.get('builtBlockCount')} "
        f"missing={report.get('missingBlockCount')} "
        f"parsedMissing={report.get('parsedMissingBlockCount')} "
        f"incomplete={report.get('incompleteBlockCount')} "
        f"revision={report.get('revision')}"
    )
    if source == "projector_terminal_detailed_info":
        print("Внимание: это fallback из DetailedInfo проектора. Количество блоков берется из панели терминала.")
        if report.get("componentTotalsComplete") is False:
            print("Внимание: часть типов блоков не удалось сопоставить с definition, поэтому компоненты могут быть неполными.")

    missing_by_def = sorted_amount_items(report.get("missingByDefinition"))
    missing_by_display = sorted_amount_items(report.get("missingByDisplayName"))
    incomplete_by_def = sorted_amount_items(report.get("incompleteByDefinition"))
    components = sorted_amount_items(report.get("componentTotals"))

    if missing_by_def:
        print("\nMissing blocks by definition:")
        for name, amount in missing_by_def[:80]:
            print(f"  {amount_text(amount):>8}  {name}")
    elif missing_by_display:
        print("\nMissing blocks from projector terminal:")
        for name, amount in missing_by_display[:80]:
            print(f"  {amount_text(amount):>8}  {name}")
    else:
        print("\nMissing blocks: none")

    unresolved = report.get("unresolvedTerminalBlocks")
    if isinstance(unresolved, list) and unresolved:
        print("\nUnresolved terminal block names, components not counted:")
        for item in unresolved[:80]:
            if isinstance(item, dict):
                print(f"  {amount_text(item.get('count')):>8}  {item.get('name')}")

    if incomplete_by_def:
        print("\nIncomplete existing projected blocks:")
        for name, amount in incomplete_by_def[:80]:
            print(f"  {amount_text(amount):>8}  {name}")

    if components:
        print("\nComponents required for missing/incomplete projection:")
        for name, amount in components:
            print(f"  {amount_text(amount):>8}  {name}")
    else:
        print("\nComponents required: none")

    if full:
        blocks = report.get("missingBlocks") if isinstance(report.get("missingBlocks"), list) else []
        incomplete = report.get("incompleteBlocks") if isinstance(report.get("incompleteBlocks"), list) else []
        if blocks:
            print("\nMissing block list:")
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                print(
                    f"  ({as_int(block.get('x'))}, {as_int(block.get('y'))}, {as_int(block.get('z'))}) "
                    f"{block.get('definition')} {block.get('name') or ''}"
                )
        if incomplete:
            print("\nIncomplete block list:")
            for block in incomplete:
                if not isinstance(block, dict):
                    continue
                print(
                    f"  ({as_int(block.get('x'))}, {as_int(block.get('y'))}, {as_int(block.get('z'))}) "
                    f"ratio={block.get('buildRatio')} {block.get('definition')} {block.get('name') or ''}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="Show missing projector blocks and required components")
    parser.add_argument("--grid", default="farpost", help="Grid name or id")
    parser.add_argument("--name", default="", help="Only projectors whose name contains this text")
    parser.add_argument("--wait", type=float, default=3.0, help="Seconds to wait for fresh report")
    parser.add_argument("--max-blocks", type=int, default=200, help="Max missing/incomplete blocks returned in report")
    parser.add_argument("--full", action="store_true", help="Print individual missing/incomplete block list")
    parser.add_argument("--json", action="store_true", help="Print raw projection reports as JSON")
    args = parser.parse_args()

    print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
    grid = None
    try:
        grid = prepare_grid(args.grid or None, auto_wake=True)
        grid.refresh_devices()
        projectors = find_projectors(grid, args.name)

        print(f"Grid: {grid.name} ({grid.grid_id})")
        print(f"Projectors: {len(projectors)}")
        if not projectors:
            return 1

        exit_code = 0
        for projector in projectors:
            report = projector.scan_projection_report(wait=args.wait, max_blocks=args.max_blocks)
            if args.json:
                print(json.dumps({"projector": projector.name, "report": report}, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print_projector_report(projector, report, full=args.full)
            if not report or not report.get("ready"):
                exit_code = 2
        return exit_code
    finally:
        if grid is not None:
            close(grid)


if __name__ == "__main__":
    raise SystemExit(main())
