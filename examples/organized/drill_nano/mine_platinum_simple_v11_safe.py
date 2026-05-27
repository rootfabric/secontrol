#!/usr/bin/env python3
"""Safe Platinum-only Nanobot mining pipeline for strict no-stone-leak mod v11.

Put this file into examples/organized/drill_nano/ next to scan_probe_mine_ore.py.

Run:
  python examples/organized/drill_nano/mine_platinum_simple_v11_safe.py --grid skynet-baza1 --amount 5000
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

from scan_probe_mine_ore import (
    WORK_MODE_VALUES,
    configure_collect_mode,
    current_has_ore,
    force_work_mode,
    format_point,
    get_item_amount,
    get_navigation_frame,
    get_ore_amount,
    point_distance_from,
    power_on_drill,
    print_raw_filters,
    read_targets,
    safe_set_raw,
    scan_ore_points,
    set_area_to_world_target,
    stop_drill,
    target_has_ore,
)

ORE = "Platinum"
Vector = Tuple[float, float, float]

KNOWN_STRICT_MARKERS = (
    "strict_no_stone_leak_v11_2026_05_27",
    "strict_no_stone_leak_v10_2026_05_27",
    "strict_no_stone_leak_v8_2026_05_27",
    "strict_no_stone_leak_v7_2026_05_27",
    "strict_no_stone_leak_v6_2026_05_27",
    "strict_no_stone_leak_v5_2026_05_27",
    "strict_collect_v2_2026_05_25",
)


def find_drill(grid: Grid, name_filter: Optional[str]) -> NanobotDrillSystemDevice:
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        raise RuntimeError("No Nanobot Drill found")

    if not name_filter:
        return drills[0]

    wanted = name_filter.lower()
    for drill in drills:
        if wanted in drill.name.lower():
            return drill

    names = ", ".join(drill.name for drill in drills)
    raise RuntimeError(f"No Nanobot Drill name contains '{name_filter}'. Available: {names}")


def find_remote_control(grid: Grid) -> RemoteControlDevice:
    devices = grid.find_devices_by_type(RemoteControlDevice)
    if not devices:
        raise RuntimeError("No Remote Control found")
    return devices[0]


def detailed_info_text(drill: NanobotDrillSystemDevice) -> str:
    drill.update()
    telemetry = drill.telemetry or {}
    props = telemetry.get("properties", {})
    values = [
        telemetry.get("detailedInfo"),
        telemetry.get("rawDetailedInfo"),
        telemetry.get("customInfo"),
    ]
    if isinstance(props, dict):
        values.extend(
            [
                props.get("DetailedInfo"),
                props.get("detailedInfo"),
                props.get("CustomInfo"),
                props.get("customInfo"),
            ]
        )
    return "\n".join(str(value) for value in values if value)


def visible_strict_markers(drill: NanobotDrillSystemDevice) -> List[str]:
    text = detailed_info_text(drill)
    return [marker for marker in KNOWN_STRICT_MARKERS if marker in text]


def require_collect_work_mode(drill: NanobotDrillSystemDevice, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        force_work_mode(drill, WORK_MODE_VALUES["Collect"], delay=0.25)
        drill.update()
        props = (drill.telemetry or {}).get("properties", {})
        raw_mode = props.get("Drill.WorkMode") if isinstance(props, dict) else None
        try:
            if int(raw_mode) == WORK_MODE_VALUES["Collect"]:
                return True
        except (TypeError, ValueError):
            pass
        print(f"WARNING: WorkMode is not Collect yet: {raw_mode}")
    return False


def power_on_collect_strict(drill: NanobotDrillSystemDevice) -> bool:
    if not require_collect_work_mode(drill):
        print("ERROR: cannot force Drill.WorkMode=2 Collect before power on")
        return False

    started = power_on_drill(
        drill,
        expected_work_mode=WORK_MODE_VALUES["Collect"],
        retries=4,
    )
    if not started:
        print("ERROR: Nanobot did not power on in Collect mode")
        stop_drill(drill, hide_area=False)
        return False

    if not require_collect_work_mode(drill):
        print("ERROR: WorkMode drifted after power on; stopping")
        stop_drill(drill, hide_area=False)
        return False

    return True


def targets_have_requested_ore(targets: List[Any], ore_subtype: str) -> bool:
    return any(target_has_ore(target, ore_subtype) for target in targets)


def reject_forbidden_targets_if_any(drill: NanobotDrillSystemDevice, label: str, target_dump: int) -> bool:
    current, targets, props = read_targets(drill)
    ore_targets = [target for target in targets if target_has_ore(target, ORE)]
    current_ok = current is not None and current_has_ore(current, targets, ORE)

    if current is not None and not current_ok:
        print(f"SAFETY STOP before mining: {label}: current target is not {ORE}: {current}")
        describe_targets(targets, ORE, target_dump)
        stop_drill(drill, hide_area=True)
        return True

    if targets and not ore_targets and not current_ok:
        print(f"SAFETY STOP before mining: {label}: Nanobot targets contain no {ORE}. Refusing to start on stale/Stone targets.")
        describe_targets(targets, ORE, target_dump)
        stop_drill(drill, hide_area=True)
        return True

    return False


def describe_targets(targets: List[Any], ore_subtype: str, limit: int) -> None:
    for index, target in enumerate(targets[:limit]):
        mark = "<-- requested" if target_has_ore(target, ore_subtype) else ""
        print(f"  target #{index:02d}: {target} {mark}")


def mine_current_point(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    amount: float,
    baseline_ore: float,
    baseline_stone: float,
    check_interval: float,
    startup_timeout: float,
    stone_safety_delta: float,
    target_dump: int,
) -> int:
    safe_set_raw(drill, "Drill.ShowArea", True)
    time.sleep(0.6)

    # Critical safety: old Stone targets can stay in Nanobot state after moving AreaOffset.
    # Do not power on if telemetry already exposes non-Platinum targets.
    if reject_forbidden_targets_if_any(drill, "preflight before OnOff", target_dump):
        return 2

    if not power_on_collect_strict(drill):
        return 2

    # Fast guard right after OnOff: the old script waited check_interval seconds,
    # which was enough for one Stone batch to enter cargo.
    fast_start = time.time()
    while time.time() - fast_start < 1.5:
        if reject_forbidden_targets_if_any(drill, "fast guard after OnOff", target_dump):
            return 2
        time.sleep(0.1)

    started_at = time.time()
    saw_requested_target = False

    while True:
        time.sleep(max(0.2, check_interval))

        current, targets, props = read_targets(drill)
        ore_targets = [target for target in targets if target_has_ore(target, ORE)]
        current_ok = current is not None and current_has_ore(current, targets, ORE)
        saw_requested_target = saw_requested_target or bool(ore_targets) or current_ok

        mined = get_ore_amount(grid, ORE) - baseline_ore
        stone_delta = get_item_amount(grid, "Stone") - baseline_stone
        elapsed = max(0.001, time.time() - started_at)
        rate = mined / elapsed
        eta = (amount - mined) / rate if rate > 0 and mined < amount else 0.0

        print(
            f"  [{elapsed:.0f}s] {ORE}: +{mined:.1f}/{amount:.1f}, "
            f"Stone +{stone_delta:.1f}, targets={len(targets)}, "
            f"PtTargets={len(ore_targets)}, rate={rate:.1f}/s, eta={eta:.0f}s, "
            f"WorkMode={props.get('Drill.WorkMode')}, current={current}"
        )

        if mined >= amount:
            print(f"OK: target reached, {ORE} +{mined:.1f}")
            stop_drill(drill, hide_area=False)
            return 0

        if stone_safety_delta >= 0 and stone_delta > stone_safety_delta:
            print(f"SAFETY STOP: Stone +{stone_delta:.1f} > +{stone_safety_delta:.1f}")
            stop_drill(drill, hide_area=False)
            return 2

        # New hard guard: if Nanobot sees only non-Platinum voxel targets, do not wait
        # until it starts drilling them. Stop this point immediately and try another scan cell.
        if targets and not ore_targets and not current_ok:
            print(f"SAFETY STOP: Nanobot targets contain no {ORE}. This is usually stale Stone target state; stopping whole run.")
            describe_targets(targets, ORE, target_dump)
            stop_drill(drill, hide_area=True)
            return 2

        # New hard guard: current target must never be non-Platinum, even before cargo delta appears.
        if current is not None and not current_ok:
            print(f"SAFETY STOP: current target is not {ORE}: {current}")
            describe_targets(targets, ORE, target_dump)
            stop_drill(drill, hide_area=False)
            return 2

        if elapsed >= startup_timeout and not saw_requested_target and mined <= 0.01:
            print(f"No {ORE} target appeared at this point, trying next point")
            stop_drill(drill, hide_area=False)
            return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine Platinum with strict no-Stone safety")
    parser.add_argument("--grid", default="skynet-baza1", help="Grid name")
    parser.add_argument("--amount", type=float, default=5000.0, help="Target Platinum delta")
    parser.add_argument("--drill-name", default=None, help="Optional Nanobot Drill name substring")
    parser.add_argument("--scan-radius", type=float, default=500.0, help="Ore detector scan radius")
    parser.add_argument("--scan-timeout", type=float, default=45.0, help="Ore detector scan timeout")
    parser.add_argument("--area-size", type=float, default=15.0, help="Nanobot area size")
    parser.add_argument("--max-points", type=int, default=60, help="Max scanned Platinum points to try; 0 means all")
    parser.add_argument("--startup-timeout", type=float, default=25.0, help="Seconds to wait for target at one point")
    parser.add_argument("--check-interval", type=float, default=2.0, help="Mining check interval")
    parser.add_argument("--filter-timeout", type=float, default=20.0, help="Filter confirmation timeout")
    parser.add_argument("--stone-safety-delta", type=float, default=20.0, help="Stop if Stone grows above this delta; -1 disables")
    parser.add_argument("--allow-missing-marker", action="store_true", help="Continue if strict mod marker is not visible in telemetry")
    parser.add_argument("--target-dump", type=int, default=12, help="How many targets to print on point reject / safety stop")
    args = parser.parse_args()

    if args.amount <= 0:
        print("ERROR: --amount must be > 0")
        return 1
    if args.scan_radius <= 0:
        print("ERROR: --scan-radius must be > 0")
        return 1
    if args.area_size <= 0:
        print("ERROR: --area-size must be > 0")
        return 1

    grid = Grid.from_name(args.grid)
    drill = find_drill(grid, args.drill_name)
    rc = find_remote_control(grid)

    print(f"Grid: {grid.name} (id={grid.grid_id})")
    print(f"Drill: {drill.name} (id={drill.device_id})")
    print(f"RC: {rc.name} (id={rc.device_id})")

    markers = visible_strict_markers(drill)
    print(f"Strict markers visible in telemetry: {markers}")
    if not markers and not args.allow_missing_marker:
        print("ERROR: no known strict marker was found in telemetry. Use --allow-missing-marker only if the game UI shows the marker.")
        return 2

    print("\n=== STEP 1: scan Platinum ===")
    points = scan_ore_points(grid, ORE, radius=args.scan_radius, timeout=args.scan_timeout)
    if not points:
        print(f"ERROR: no {ORE} points found by ore detector")
        return 3

    print("\n=== STEP 2: navigation frame ===")
    drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)
    points.sort(key=lambda point: point_distance_from(point, drill_world))
    if args.max_points > 0:
        points = points[: args.max_points]

    print(f"Selected points: {len(points)}")
    for index, point in enumerate(points[:15], start=1):
        print(
            f"  #{index:02d}: dist={point_distance_from(point, drill_world):.1f}m "
            f"content={point.get('content', 0):.1f} pos={format_point(point['position'])}"
        )

    print("\n=== STEP 3: configure filters ===")
    if not configure_collect_mode(drill=drill, ore_subtype=ORE, use_conveyor=True, filter_timeout=args.filter_timeout):
        print("ERROR: strict Platinum filter was not confirmed")
        print_raw_filters(drill)
        return 4

    print("Filters confirmed: Collect + Ore + Platinum only")
    print_raw_filters(drill)

    baseline_ore = get_ore_amount(grid, ORE)
    baseline_stone = get_item_amount(grid, "Stone")
    print(f"\nBaseline {ORE}: {baseline_ore:.1f}")
    print(f"Baseline Stone: {baseline_stone:.1f}")

    print("\n=== STEP 4: aim and mine ===")
    for index, point in enumerate(points, start=1):
        target_world: Vector = point["position"]
        print(f"\n--- Point {index}/{len(points)}: {format_point(target_world)} ---")

        stop_drill(drill, hide_area=False)
        if not require_collect_work_mode(drill):
            print("ERROR: cannot set Collect mode before area offset")
            return 5

        set_area_to_world_target(
            drill=drill,
            drill_world=drill_world,
            left=left,
            up=up,
            fwd=fwd,
            target_world=target_world,
            area_size=args.area_size,
        )

        result = mine_current_point(
            grid=grid,
            drill=drill,
            amount=args.amount,
            baseline_ore=baseline_ore,
            baseline_stone=baseline_stone,
            check_interval=args.check_interval,
            startup_timeout=args.startup_timeout,
            stone_safety_delta=args.stone_safety_delta,
            target_dump=args.target_dump,
        )

        if result == 0:
            return 0
        if result == 2:
            return 6

    print(f"ERROR: no scanned {ORE} point could be mined safely")
    stop_drill(drill, hide_area=False)
    return 7


if __name__ == "__main__":
    raise SystemExit(main())
