#!/usr/bin/env python3
"""
set_nanodrill_area.py — Point Nanobot Drill area at a world coordinate.

Usage:
    python examples/organized/drill_nano/set_nanodrill_area.py --grid <name> --target <x> <y> <z>
    python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target -50626.3 146646.9 -137739.8
    python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target -50626.3 146646.9 -137739.8 --dry-run

Flags:
    --dry-run       Show offset only, do not send commands
    --reset-area    Reset offsets to 0 before setting new target
    --drill-name    Filter drill by name substring
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


def cross(a: dict, b: dict) -> dict:
    return {
        "x": a["y"] * b["z"] - a["z"] * b["y"],
        "y": a["z"] * b["x"] - a["x"] * b["z"],
        "z": a["x"] * b["y"] - a["y"] * b["x"],
    }


def get_drill_world_pos(rc_pos: dict, orient: dict, drill_local: tuple) -> dict:
    fwd = orient["forward"]
    up = orient["up"]
    right = orient.get("right")
    left = orient.get("left")

    if right:
        rx, ry, rz = right["x"], right["y"], right["z"]
    elif left:
        rx, ry, rz = -left["x"], -left["y"], -left["z"]
    else:
        rx, ry, rz = fwd["y"] * up["z"] - fwd["z"] * up["y"], \
                      fwd["z"] * up["x"] - fwd["x"] * up["z"], \
                      fwd["x"] * up["y"] - fwd["y"] * up["x"]

    lx, ly, lz = drill_local
    return {
        "x": rc_pos["x"] + lx * rx + ly * up["x"] + lz * fwd["x"],
        "y": rc_pos["y"] + lx * ry + ly * up["y"] + lz * fwd["y"],
        "z": rc_pos["z"] + lx * rz + ly * up["z"] + lz * fwd["z"],
    }


def compute_area_offset(rc_pos: dict, orient: dict, drill_local: tuple, target_world: tuple) -> tuple:
    fwd = orient["forward"]
    up = orient["up"]
    right = orient.get("right")
    left = orient.get("left")

    if right:
        rx, ry, rz = right["x"], right["y"], right["z"]
    elif left:
        rx, ry, rz = -left["x"], -left["y"], -left["z"]
    else:
        rx, ry, rz = fwd["y"] * up["z"] - fwd["z"] * up["y"], \
                      fwd["z"] * up["x"] - fwd["x"] * up["z"], \
                      fwd["x"] * up["y"] - fwd["y"] * up["x"]

    drill_pos = get_drill_world_pos(rc_pos, orient, drill_local)

    ddx = target_world[0] - drill_pos["x"]
    ddy = target_world[1] - drill_pos["y"]
    ddz = target_world[2] - drill_pos["z"]

    local_fwd = ddx * fwd["x"] + ddy * fwd["y"] + ddz * fwd["z"]
    local_up = ddx * up["x"] + ddy * up["y"] + ddz * up["z"]
    local_right = ddx * rx + ddy * ry + ddz * rz

    return local_fwd, local_up, local_right


def get_drill_local_offset(grid: Grid, drill: NanobotDrillSystemDevice) -> tuple:
    if not hasattr(grid, "blocks") or not grid.blocks:
        return (0.0, 0.0, 0.0)

    drill_id = str(drill.device_id)

    if isinstance(grid.blocks, dict):
        for bid, block in grid.blocks.items():
            if str(block.block_id) == drill_id:
                lp = block.local_position
                if lp:
                    return (float(lp[0]), float(lp[1]), float(lp[2]))

    return (0.0, 0.0, 0.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Set Nanobot Drill area offset to a world target")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--target", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"),
                        help="World coordinates of target")
    parser.add_argument("--drill-name", default=None, help="Drill custom name (optional, uses first found)")
    parser.add_argument("--dry-run", action="store_true", help="Show offset only, do not send commands")
    parser.add_argument("--reset-area", action="store_true", help="Reset area offsets to 0 before setting target")

    args = parser.parse_args()
    target_world = tuple(args.target)

    print(f"Connecting to grid '{args.grid}'...")
    grid = Grid.from_name(args.grid)
    time.sleep(1)

    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("ERROR: No Nanobot Drill found on grid")
        return 1

    if args.drill_name:
        drill = next((d for d in drills if args.drill_name.lower() in d.name.lower()), None)
        if not drill:
            print(f"ERROR: Drill with name containing '{args.drill_name}' not found")
            return 1
    else:
        drill = drills[0]

    rc_devices = grid.find_devices_by_type(RemoteControlDevice)
    rc = rc_devices[0] if rc_devices else None

    print(f"Drill: {drill.name} (id={drill.device_id})")

    rc_pos = None
    orient = None

    if rc:
        rc.update()
        time.sleep(0.5)
        rc.update()
        rc_tel = rc.telemetry or {}
        rc_pos = rc_tel.get("position", {})
        orient = rc_tel.get("orientation", {})
        print(f"RC: {rc.name} (id={rc.device_id})")
    else:
        print("WARNING: No Remote Control found, using drill position")
        drill.update()
        tel = drill.telemetry or {}
        props = tel.get("properties", {})
        rc_pos = props.get("Position", props.get("position", {}))
        orient = props.get("Orientation", props.get("orientation", {}))

    if not rc_pos or not orient:
        print("ERROR: No position/orientation data available")
        return 1

    print(f"Target: ({target_world[0]:.1f}, {target_world[1]:.1f}, {target_world[2]:.1f})")
    print(f"RC/Ship position: ({rc_pos.get('x', 0):.1f}, {rc_pos.get('y', 0):.1f}, {rc_pos.get('z', 0):.1f})")

    drill_local = get_drill_local_offset(grid, drill)
    print(f"Drill local offset from RC: ({drill_local[0]:.1f}, {drill_local[1]:.1f}, {drill_local[2]:.1f})")

    fwd = orient["forward"]
    up = orient["up"]

    print(f"Forward: ({fwd['x']:.3f}, {fwd['y']:.3f}, {fwd['z']:.3f})")
    print(f"Up:      ({up['x']:.3f}, {up['y']:.3f}, {up['z']:.3f})")

    local_fwd, local_up, local_right = compute_area_offset(rc_pos, orient, drill_local, target_world)

    print("\nArea offset (ship-local):")
    print(f"  FrontBack:  {local_fwd:+.2f}m")
    print(f"  UpDown:     {local_up:+.2f}m")
    print(f"  LeftRight:  {local_right:+.2f}m")

    drill_pos = get_drill_world_pos(rc_pos, orient, drill_local)
    dist_to_target = math.sqrt(
        (target_world[0] - drill_pos["x"])**2 +
        (target_world[1] - drill_pos["y"])**2 +
        (target_world[2] - drill_pos["z"])**2
    )
    print(f"Drill to target distance: {dist_to_target:.1f}m")

    AREA_HALF = 37.5
    if dist_to_target < AREA_HALF:
        print(f"  [OK] Target within drill area ({AREA_HALF}m radius)")
    elif dist_to_target < AREA_HALF * 1.5:
        print("  [WARN] Target at edge of drill area")
    else:
        print("  [WARN] Target outside drill area — offset may not reach")

    if args.dry_run:
        print("\n[Dry run — no commands sent]")
        return 0

    if args.reset_area:
        print("\nResetting area offsets to 0...")
        drill.set_raw_property("Drill.AreaOffsetUpDown", 0.0)
        drill.set_raw_property("Drill.AreaOffsetFrontBack", 0.0)
        drill.set_raw_property("Drill.AreaOffsetLeftRight", 0.0)
        time.sleep(0.3)

    print("\nSetting area offset...")
    drill.set_raw_property("Drill.AreaOffsetFrontBack", round(local_fwd, 2))
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetUpDown", round(local_up, 2))
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetLeftRight", round(local_right, 2))

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())