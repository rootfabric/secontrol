#!/usr/bin/env python3
"""Point Nanobot Drill at a world target and mine Stone into cargo.

Configures:
  - WorkMode = Drill (1)
  - OreFilter = ["Stone"], CollectFilter = ["Stone"] (v12 strict)
  - UseConveyor = True (stone goes to cargo, not destroyed)
  - AreaOffset points at target world coordinate

Usage:
  python examples/organized/drill_nano/mine_stone_only.py ^
    --grid skynet-farpost0 ^
    --target -137295.756 -111094.327 -82015.03 ^
    --area-size 30

  # Use asteroid center from space_survey --gps, or any voxel coord near the base.
"""

from __future__ import annotations

import argparse
import math
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
    force_work_mode,
    get_item_amount,
    get_navigation_frame,
    power_on_drill,
    print_raw_filters,
    read_targets,
    safe_action,
    safe_set_raw,
    send_collect_filter_direct,
    send_ore_filter_direct,
    set_area_to_world_target,
    stop_drill,
    target_has_ore,
)

Vector = Tuple[float, float, float]


def get_stone_amount(grid: Grid) -> float:
    return get_item_amount(grid, "Stone")


def get_drill_world_pos(rc_pos: dict, orient: dict, drill_local: tuple) -> Vector:
    fwd = orient["forward"]
    up = orient["up"]
    fwd_arr = (fwd["x"], fwd["y"], fwd["z"])
    up_arr = (up["x"], up["y"], up["z"])
    right = (
        fwd_arr[1] * up_arr[2] - fwd_arr[2] * up_arr[1],
        fwd_arr[2] * up_arr[0] - fwd_arr[0] * up_arr[2],
        fwd_arr[0] * up_arr[1] - fwd_arr[1] * up_arr[0],
    )
    lx, ly, lz = drill_local
    return (
        rc_pos["x"] + lx * right[0] + ly * up_arr[0] + lz * fwd_arr[0],
        rc_pos["y"] + lx * right[1] + ly * up_arr[1] + lz * fwd_arr[1],
        rc_pos["z"] + lx * right[2] + ly * up_arr[2] + lz * fwd_arr[2],
    )


def configure_stone_drill_mode(drill: NanobotDrillSystemDevice, filter_delay: float) -> None:
    """Configure Nanobot for Stone mining in Drill mode with conveyor ON."""
    print("Configuring Stone mining (Drill mode, conveyor ON)...")

    stop_drill(drill, hide_area=True)
    time.sleep(0.4)

    for action_id in ("CollectIfIdle_Off", "TerrainClearingMode_Off"):
        safe_action(drill, action_id)
        time.sleep(0.05)

    for prop in (
        "UseConveyor",
        "Drill.UseConveyor",
        "DrillSystem.UseConveyor",
        "Drill.CollectIfIdle",
        "Drill.TerrainClearingMode",
        "DrillSystem.CollectIfIdle",
        "DrillSystem.TerrainClearingMode",
    ):
        value = True if prop.endswith("UseConveyor") else False
        safe_set_raw(drill, prop, value)
        time.sleep(0.04)

    safe_set_raw(drill, "Drill.ScriptControlled", True)
    time.sleep(0.4)

    send_collect_filter_direct(drill, ["Stone"])
    time.sleep(filter_delay)

    send_ore_filter_direct(
        drill,
        ["Stone"],
        work_mode_value=WORK_MODE_VALUES["Drill"],
        apply_collect_filter=False,
    )
    time.sleep(filter_delay)

    force_work_mode(drill, WORK_MODE_VALUES["Drill"], delay=0.3)

    safe_set_raw(drill, "Drill.ScriptControlled", False)
    time.sleep(0.3)
    try:
        drill.set_script_controlled_action(False)
    except Exception:
        pass
    time.sleep(0.2)

    force_work_mode(drill, WORK_MODE_VALUES["Drill"], delay=0.3)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine Stone from voxels with Nanobot Drill")
    parser.add_argument("--grid", required=True)
    parser.add_argument("--target", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"),
                        help="World coordinate to point the drill at")
    parser.add_argument("--area-size", type=float, default=30.0)
    parser.add_argument("--drill-name", default=None)
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="Max run time in seconds; 0 = until amount reached or Ctrl+C")
    parser.add_argument("--amount", type=float, default=0.0,
                        help="Target amount of stone in inventory (L); 0 = no limit")
    parser.add_argument("--check-interval", type=float, default=5.0)
    parser.add_argument("--filter-delay", type=float, default=0.5)
    parser.add_argument("--no-restore", action="store_true",
                        help="Leave drill in Drill+Stone mode after exit")
    args = parser.parse_args()

    target: Vector = (float(args.target[0]), float(args.target[1]), float(args.target[2]))

    grid = Grid.from_name(args.grid)
    print(f"Grid: {grid.name} (id={grid.grid_id})")

    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("ERROR: No Nanobot Drill on grid")
        return 1
    if args.drill_name:
        wanted = args.drill_name.lower()
        drill = next((d for d in drills if wanted in d.name.lower()), None)
        if not drill:
            print(f"ERROR: no drill matching '{args.drill_name}'. Available: {[d.name for d in drills]}")
            return 1
    else:
        drill = drills[0]
    print(f"Drill: {drill.name} (id={drill.device_id})")

    rc_devices = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_devices:
        print("ERROR: No Remote Control on grid (needed to compute area offset)")
        return 1
    rc = rc_devices[0]
    print(f"RC: {rc.name} (id={rc.device_id})")

    drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)
    print(f"Drill world pos: ({drill_world[0]:.2f}, {drill_world[1]:.2f}, {drill_world[2]:.2f})")
    print(f"Target:          ({target[0]:.2f}, {target[1]:.2f}, {target[2]:.2f})")
    dist = math.sqrt(
        (target[0] - drill_world[0]) ** 2
        + (target[1] - drill_world[1]) ** 2
        + (target[2] - drill_world[2]) ** 2
    )
    print(f"Distance: {dist:.1f}m")

    if dist > 1000.0:
        print(f"WARNING: target is {dist:.1f}m away; drill offset max is 1000m. Move closer.")

    baseline_stone = get_stone_amount(grid)
    print(f"Baseline stone in cargo: {baseline_stone:.1f} L")

    configure_stone_drill_mode(drill, args.filter_delay)
    print_raw_filters(drill)

    set_area_to_world_target(
        drill=drill,
        drill_world=drill_world,
        left=left,
        up=up,
        fwd=fwd,
        target_world=target,
        area_size=args.area_size,
    )

    safe_set_raw(drill, "Drill.ShowArea", True)
    time.sleep(0.3)

    print(f"Starting drill in Drill+Stone mode (target {args.amount:.0f} L, max {args.seconds:.0f}s)...")
    started = power_on_drill(
        drill,
        expected_work_mode=WORK_MODE_VALUES["Drill"],
        retries=4,
    )
    if not started:
        print("ERROR: drill did not power on")
        stop_drill(drill, hide_area=False)
        return 2

    started_at = time.time()
    try:
        while True:
            time.sleep(max(0.2, args.check_interval))
            elapsed = time.time() - started_at
            current_stone = get_stone_amount(grid)
            delta = current_stone - baseline_stone
            rate = delta / elapsed if elapsed > 0 else 0.0
            current, targets, props = read_targets(drill)
            stone_targets = [t for t in targets if target_has_ore(t, "Stone")]

            print(
                f"  [{elapsed:6.1f}s] stone={current_stone:8.1f} L "
                f"delta=+{delta:8.1f} L rate={rate:6.1f} L/s "
                f"targets={len(targets)} (stone={len(stone_targets)}) "
                f"WorkMode={props.get('Drill.WorkMode')} current={current}"
            )

            if args.amount > 0 and delta >= args.amount:
                print(f"Reached target amount: +{delta:.1f} L")
                break
            if args.seconds > 0 and elapsed >= args.seconds:
                print(f"Reached max time: {elapsed:.1f}s")
                break
    except KeyboardInterrupt:
        print("Interrupted by user")

    stop_drill(drill, hide_area=False)
    time.sleep(0.5)

    final_stone = get_stone_amount(grid)
    print(f"\nDone. Stone in cargo: {final_stone:.1f} L (delta +{final_stone - baseline_stone:.1f} L)")

    if not args.no_restore:
        print("Leaving drill OFF. Re-run with another mode to use it.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
