#!/usr/bin/env python3
"""Point Nanobot Drill area at a world coordinate.

This version is rotation-safe: AreaOffset is calculated in the Nanobot block's
own orientation, not in a hardcoded grid orientation.

Usage:
    python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target -50626.3 146646.9 -137739.8
    python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target -50626.3 146646.9 -137739.8 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

from nanodrill_area_frame import (
    get_block_local_position,
    get_drill_local_offset,
    get_navigation_frame,
    set_area_to_world_target,
    v_add,
    v_len,
    v_mul,
    v_sub,
)

Vector = Tuple[float, float, float]


def format_point(point: Vector) -> str:
    return f"({point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f})"


def find_drill(grid: Grid, name_filter: Optional[str]) -> NanobotDrillSystemDevice:
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        raise RuntimeError("No Nanobot Drill found on grid")

    if not name_filter:
        return drills[0]

    wanted = name_filter.lower()
    for drill in drills:
        if wanted in drill.name.lower():
            return drill

    available = ", ".join(drill.name for drill in drills)
    raise RuntimeError(f"Drill with name containing {name_filter!r} not found. Available: {available}")


def find_remote_control(grid: Grid) -> RemoteControlDevice:
    devices = grid.find_devices_by_type(RemoteControlDevice)
    if not devices:
        raise RuntimeError("No Remote Control found on grid")
    return devices[0]


def set_area_size(drill: NanobotDrillSystemDevice, width: float, height: float, depth: float) -> None:
    for prop, value in (
        ("Drill.AreaWidth", width),
        ("Drill.AreaHeight", height),
        ("Drill.AreaDepth", depth),
    ):
        drill.set_raw_property(prop, float(value))
        time.sleep(0.08)


def print_actual_area(drill: NanobotDrillSystemDevice) -> None:
    drill.update()
    props = (drill.telemetry or {}).get("properties", {})
    print("Actual area properties:")
    for prop in (
        "Drill.AreaOffsetFrontBack",
        "Drill.AreaOffsetUpDown",
        "Drill.AreaOffsetLeftRight",
        "Drill.AreaWidth",
        "Drill.AreaHeight",
        "Drill.AreaDepth",
        "Drill.ShowArea",
    ):
        print(f"  {prop}: {props.get(prop)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Set Nanobot Drill area offset to a world target")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--target", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"), help="World target coordinates")
    parser.add_argument("--drill-name", default=None, help="Optional Nanobot Drill name substring")
    parser.add_argument("--area-size", type=float, default=0.0, help="Set width/height/depth to this value; 0 keeps current size")
    parser.add_argument("--area-width", type=float, default=None, help="Area width override")
    parser.add_argument("--area-height", type=float, default=None, help="Area height override")
    parser.add_argument("--area-depth", type=float, default=None, help="Area depth override")
    parser.add_argument("--dry-run", action="store_true", help="Show offset only, do not send commands")
    parser.add_argument("--reset-area", action="store_true", help="Reset offsets to 0 before setting target")
    parser.add_argument("--show-area", action="store_true", help="Turn Nanobot area visualization on after setting")
    args = parser.parse_args()

    target_world: Vector = (float(args.target[0]), float(args.target[1]), float(args.target[2]))

    grid = Grid.from_name(args.grid)
    drill = find_drill(grid, args.drill_name)
    rc = find_remote_control(grid)

    print(f"Grid: {grid.name} (id={grid.grid_id})")
    print(f"Drill: {drill.name} (id={drill.device_id})")
    print(f"RC: {rc.name} (id={rc.device_id})")
    print(f"Target: {format_point(target_world)}")

    drill_local = get_block_local_position(grid, drill.device_id)
    rc_local = get_block_local_position(grid, rc.device_id)
    drill_from_rc = get_drill_local_offset(grid, drill, rc)
    if drill_local is not None:
        print(f"Drill grid-local position: {format_point(drill_local)}")
    if rc_local is not None:
        print(f"RC grid-local position:    {format_point(rc_local)}")
    if drill_from_rc is not None:
        print(f"Drill local offset from RC: {format_point(drill_from_rc)}")

    drill_world, left_right_axis, up_down_axis, front_back_axis = get_navigation_frame(grid, drill, rc)
    delta = v_sub(target_world, drill_world)
    left_right = delta[0] * left_right_axis[0] + delta[1] * left_right_axis[1] + delta[2] * left_right_axis[2]
    up_down = delta[0] * up_down_axis[0] + delta[1] * up_down_axis[1] + delta[2] * up_down_axis[2]
    front_back = delta[0] * front_back_axis[0] + delta[1] * front_back_axis[1] + delta[2] * front_back_axis[2]

    area_center = v_add(
        drill_world,
        v_add(
            v_mul(left_right_axis, left_right),
            v_add(v_mul(up_down_axis, up_down), v_mul(front_back_axis, front_back)),
        ),
    )
    miss = v_len(v_sub(area_center, target_world))

    print("\nArea offset from Nanobot block orientation:")
    print(f"  FrontBack:  {front_back:+.2f}m")
    print(f"  UpDown:     {up_down:+.2f}m")
    print(f"  LeftRight:  {left_right:+.2f}m")
    print("\nVerification:")
    print(f"  Drill world position: {format_point(drill_world)}")
    print(f"  Area center world:    {format_point(area_center)}")
    print(f"  Target miss:          {miss:.3f}m")
    print(f"  Drill to target:      {v_len(delta):.1f}m")

    max_axis = max(abs(front_back), abs(up_down), abs(left_right))
    if max_axis > 1000.0:
        print(f"WARNING: one AreaOffset axis is {max_axis:.1f}m; Nanobot usually clamps offsets around 1000m.")

    if args.dry_run:
        print("\nDry run: no commands were sent.")
        return 0

    if args.reset_area:
        print("\nResetting area offsets to 0...")
        for prop in (
            "Drill.AreaOffsetFrontBack",
            "Drill.AreaOffsetUpDown",
            "Drill.AreaOffsetLeftRight",
        ):
            drill.set_raw_property(prop, 0.0)
            time.sleep(0.08)

    size_for_helper = args.area_size if args.area_size > 0 else 1.0
    if args.area_width is not None or args.area_height is not None or args.area_depth is not None:
        width = args.area_width if args.area_width is not None else (args.area_size if args.area_size > 0 else 1.0)
        height = args.area_height if args.area_height is not None else (args.area_size if args.area_size > 0 else 1.0)
        depth = args.area_depth if args.area_depth is not None else (args.area_size if args.area_size > 0 else 1.0)
        size_for_helper = max(width, height, depth)
    else:
        width = height = depth = args.area_size if args.area_size > 0 else 0.0

    print("\nSetting Nanobot area...")
    set_area_to_world_target(
        drill=drill,
        drill_world=drill_world,
        left=left_right_axis,
        up=up_down_axis,
        fwd=front_back_axis,
        target_world=target_world,
        area_size=size_for_helper,
    )

    if width > 0 and height > 0 and depth > 0:
        set_area_size(drill, width, height, depth)

    if args.show_area:
        drill.set_raw_property("Drill.ShowArea", True)
        time.sleep(0.1)

    print_actual_area(drill)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
