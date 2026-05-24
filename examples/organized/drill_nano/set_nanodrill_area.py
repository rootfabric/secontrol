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

# ---------------------------------------------------------------
# DRILL AXIS MAP — how drill-local axes relate to grid axes
# ---------------------------------------------------------------
# Grid:  [Left=X, Up=Y, Forward=Z]
# Drill: [LeftRight, UpDown, FrontBack]
#
# Each entry: (grid_axis_index, sign)
#   grid_axis_index: 0=X(Left), 1=Y(Up), 2=Z(Forward)
#   sign: +1 or -1
#
# On skynet-baza0 the Nanobot Drill has BlockOrientation Forward=Down, Up=Forward,
# but the mod's AreaOffsetFrontBack follows grid Up with the observed positive sign.
#   drill_right     = grid_left    -> LeftRight = +grid[0]
#   drill_up        = grid_forward -> UpDown    = +grid[2]
#   drill_forward   = grid_up      -> FrontBack = +grid[1]
#
# Identity (default, drill aligned with grid):
#   DRILL_AXIS_MAP = {"LeftRight": (0, 1), "UpDown": (1, 1), "FrontBack": (2, 1)}
#
DRILL_AXIS_MAP = {
    "LeftRight": (0, 1),  # grid X/Left -> drill LeftRight
    "UpDown":    (2, 1),  # grid Z → drill UpDown  (drill_up = grid_forward)
    "FrontBack": (1, 1),  # grid Y → drill FrontBack (observed Z/depth axis)
}


def cross(a: dict, b: dict) -> dict:
    return {
        "x": a["y"] * b["z"] - a["z"] * b["y"],
        "y": a["z"] * b["x"] - a["x"] * b["z"],
        "z": a["x"] * b["y"] - a["y"] * b["x"],
    }


def get_grid_left_axis(orient: dict) -> tuple:
    """Return Space Engineers grid-local +X axis in world coordinates."""
    left = orient.get("left")
    if left:
        return left["x"], left["y"], left["z"]

    right = orient.get("right")
    if right:
        return -right["x"], -right["y"], -right["z"]

    fwd = orient["forward"]
    up = orient["up"]
    right_from_cross = cross(fwd, up)
    return -right_from_cross["x"], -right_from_cross["y"], -right_from_cross["z"]


def get_drill_world_pos(rc_pos: dict, orient: dict, drill_local: tuple) -> dict:
    fwd = orient["forward"]
    up = orient["up"]
    lx_axis, ly_axis, lz_axis = get_grid_left_axis(orient)

    lx, ly, lz = drill_local
    return {
        "x": rc_pos["x"] + lx * lx_axis + ly * up["x"] + lz * fwd["x"],
        "y": rc_pos["y"] + lx * ly_axis + ly * up["y"] + lz * fwd["y"],
        "z": rc_pos["z"] + lx * lz_axis + ly * up["z"] + lz * fwd["z"],
    }


def compute_area_offset(rc_pos: dict, orient: dict, drill_local: tuple, target_world: tuple) -> tuple:
    fwd = orient["forward"]
    up = orient["up"]
    lx_axis, ly_axis, lz_axis = get_grid_left_axis(orient)

    drill_pos = get_drill_world_pos(rc_pos, orient, drill_local)

    ddx = target_world[0] - drill_pos["x"]
    ddy = target_world[1] - drill_pos["y"]
    ddz = target_world[2] - drill_pos["z"]

    local_fwd = ddx * fwd["x"] + ddy * fwd["y"] + ddz * fwd["z"]
    local_up = ddx * up["x"] + ddy * up["y"] + ddz * up["z"]
    local_left = ddx * lx_axis + ddy * ly_axis + ddz * lz_axis

    return local_fwd, local_up, local_left


def get_block_local_position(grid: Grid, device_id: int | str) -> tuple | None:
    if not hasattr(grid, "blocks") or not grid.blocks:
        return None

    wanted_id = str(device_id)

    if isinstance(grid.blocks, dict):
        for bid, block in grid.blocks.items():
            if str(block.block_id) == wanted_id:
                lp = block.local_position
                if lp:
                    return (float(lp[0]), float(lp[1]), float(lp[2]))

    return None


def get_drill_local_offset(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice | None = None,
) -> tuple:
    drill_pos = get_block_local_position(grid, drill.device_id)
    if drill_pos is None:
        return (0.0, 0.0, 0.0)

    if rc is None:
        return drill_pos

    rc_pos = get_block_local_position(grid, rc.device_id)
    if rc_pos is None:
        return drill_pos

    return (
        drill_pos[0] - rc_pos[0],
        drill_pos[1] - rc_pos[1],
        drill_pos[2] - rc_pos[2],
    )


def world_from_drill_offset(
    drill_pos: dict,
    orient: dict,
    frontback: float,
    updown: float,
    leftright: float,
) -> tuple:
    grid_vec = [0.0, 0.0, 0.0]
    for prop_name, value in (
        ("FrontBack", frontback),
        ("UpDown", updown),
        ("LeftRight", leftright),
    ):
        axis, sign = DRILL_AXIS_MAP[prop_name]
        grid_vec[axis] = value / sign

    left = get_grid_left_axis(orient)
    up = orient["up"]
    fwd = orient["forward"]
    local_left, local_up, local_fwd = grid_vec

    return (
        drill_pos["x"] + local_left * left[0] + local_up * up["x"] + local_fwd * fwd["x"],
        drill_pos["y"] + local_left * left[1] + local_up * up["y"] + local_fwd * fwd["y"],
        drill_pos["z"] + local_left * left[2] + local_up * up["z"] + local_fwd * fwd["z"],
    )


def distance(a: tuple, b: tuple) -> float:
    return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2 + (a[2] - b[2])**2)


def format_point(p: tuple) -> str:
    return f"({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f})"


def get_drill_local_position(grid: Grid, drill: NanobotDrillSystemDevice) -> tuple:
    pos = get_block_local_position(grid, drill.device_id)
    if pos:
        return pos
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

    drill_local_pos = get_drill_local_position(grid, drill)
    rc_local_pos = get_block_local_position(grid, rc.device_id) if rc else None
    drill_local = get_drill_local_offset(grid, drill, rc)
    print(f"Drill grid-local position: ({drill_local_pos[0]:.1f}, {drill_local_pos[1]:.1f}, {drill_local_pos[2]:.1f})")
    if rc_local_pos:
        print(f"RC grid-local position:    ({rc_local_pos[0]:.1f}, {rc_local_pos[1]:.1f}, {rc_local_pos[2]:.1f})")
    print(f"Drill local offset from RC: ({drill_local[0]:.1f}, {drill_local[1]:.1f}, {drill_local[2]:.1f})")

    fwd = orient["forward"]
    up = orient["up"]

    print(f"Forward: ({fwd['x']:.3f}, {fwd['y']:.3f}, {fwd['z']:.3f})")
    print(f"Up:      ({up['x']:.3f}, {up['y']:.3f}, {up['z']:.3f})")

    local_fwd, local_up, local_left = compute_area_offset(rc_pos, orient, drill_local, target_world)

    grid_vec = [local_left, local_up, local_fwd]

    def remap(axis, sign):
        return grid_vec[axis] * sign

    drill_leftright = remap(*DRILL_AXIS_MAP["LeftRight"])
    drill_updown    = remap(*DRILL_AXIS_MAP["UpDown"])
    drill_frontback = remap(*DRILL_AXIS_MAP["FrontBack"])

    print("\nArea offset (ship-local / grid frame):")
    print(f"  Grid Left/X:  {local_left:+.2f}m")
    print(f"  Grid Up:      {local_up:+.2f}m")
    print(f"  Grid Forward: {local_fwd:+.2f}m")
    print("\nArea offset (drill-local after axis map):")
    print(f"  FrontBack:  {drill_frontback:+.2f}m")
    print(f"  UpDown:     {drill_updown:+.2f}m")
    print(f"  LeftRight:  {drill_leftright:+.2f}m")

    drill_pos = get_drill_world_pos(rc_pos, orient, drill_local)
    area_center = world_from_drill_offset(
        drill_pos,
        orient,
        drill_frontback,
        drill_updown,
        drill_leftright,
    )
    print("\nVerification:")
    print(f"  Drill world position: {format_point((drill_pos['x'], drill_pos['y'], drill_pos['z']))}")
    print(f"  Area center world:    {format_point(area_center)}")
    print(f"  Target miss:          {distance(area_center, target_world):.3f}m")

    dist_to_target = math.sqrt(
        (target_world[0] - drill_pos["x"])**2 +
        (target_world[1] - drill_pos["y"])**2 +
        (target_world[2] - drill_pos["z"])**2
    )
    print(f"Drill to target distance: {dist_to_target:.1f}m")

    MAX_OFFSET_PER_AXIS = 1000.0
    max_axis_comp = max(abs(drill_frontback), abs(drill_updown), abs(drill_leftright))
    if max_axis_comp <= MAX_OFFSET_PER_AXIS:
        print(f"  [OK] All offset components ≤ {MAX_OFFSET_PER_AXIS:.0f}m — zone will reach target")
    else:
        print(f"  [WARN] Offset component {max_axis_comp:.1f}m exceeds {MAX_OFFSET_PER_AXIS:.0f}m limit — zone may not reach")

    if args.dry_run:
        print("\n[Dry run — no commands sent]")
        return 0

    if args.reset_area:
        print("\nResetting area offsets to 0...")
        drill.set_raw_property("Drill.AreaOffsetFrontBack", 0.0)
        drill.set_raw_property("Drill.AreaOffsetUpDown", 0.0)
        drill.set_raw_property("Drill.AreaOffsetLeftRight", 0.0)
        time.sleep(0.3)

    print("\nSetting area offset...")
    drill.set_raw_property("Drill.AreaOffsetFrontBack", round(drill_frontback, 2))
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetUpDown", round(drill_updown, 2))
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetLeftRight", round(drill_leftright, 2))

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
