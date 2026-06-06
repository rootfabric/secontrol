#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except Exception:
    pass

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice


def compact(value: Any, limit: int = 900) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def print_vector_block(title: str, value: Any) -> None:
    if isinstance(value, dict) and {"x", "y", "z"}.issubset(value.keys()):
        print(f"  {title}: x={float(value['x']):+.6f}, y={float(value['y']):+.6f}, z={float(value['z']):+.6f}")
    else:
        print(f"  {title}: {compact(value)}")



def find_grid_block(grid: Grid, device_id: int | str) -> Optional[Any]:
    if not hasattr(grid, "blocks") or not grid.blocks:
        return None
    wanted = str(device_id)
    blocks = grid.blocks.values() if isinstance(grid.blocks, dict) else grid.blocks
    for block in blocks:
        if isinstance(block, dict):
            raw_id = block.get("id") or block.get("blockId") or block.get("entityId")
            if str(raw_id) == wanted:
                return block
            continue
        if str(getattr(block, "block_id", "")) == wanted:
            return block
    return None


def block_value(block: Any, *keys: str) -> Any:
    if isinstance(block, dict):
        for key in keys:
            if key in block:
                return block.get(key)
    extra = getattr(block, "extra", None)
    if isinstance(extra, dict):
        for key in keys:
            if key in extra:
                return extra.get(key)
    for key in keys:
        if hasattr(block, key):
            return getattr(block, key)
    return None

def main() -> int:
    parser = argparse.ArgumentParser(description="Check Nanobot Drill strict patch and transform telemetry")
    parser.add_argument("--grid", default="skynet-baza1")
    parser.add_argument("--drill-name", default=None)
    args = parser.parse_args()

    grid = Grid.from_name(args.grid)
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if args.drill_name:
        wanted = args.drill_name.lower()
        drills = [drill for drill in drills if wanted in drill.name.lower()]
    if not drills:
        print("ERROR: Nanobot Drill not found")
        return 1

    drill = drills[0]
    print(f"Grid: {grid.name} ({grid.grid_id})")
    print(f"Drill: {drill.name} ({drill.device_id})")

    for _ in range(3):
        try:
            drill.wait_for_telemetry(timeout=2.0, wait_for_new=True, need_update=True)
        except Exception:
            drill.update()
        time.sleep(0.3)

    telemetry = drill.telemetry or {}
    props = as_dict(telemetry.get("properties"))
    area = as_dict(telemetry.get("area"))
    orientation = as_dict(telemetry.get("orientation"))
    axis = as_dict(area.get("axis"))

    print("\nTop-level Nanobot telemetry:")
    print(f"  deviceKind: {telemetry.get('deviceKind')}")
    print(f"  nanodrillTransformTelemetryVersion: {telemetry.get('nanodrillTransformTelemetryVersion')}")
    print_vector_block("position", telemetry.get("position"))
    print(f"  orientation keys: {sorted(orientation.keys()) if orientation else []}")
    if orientation:
        for key in ("forward", "backward", "up", "down", "left", "right"):
            if key in orientation:
                print_vector_block(f"orientation.{key}", orientation.get(key))
    print(f"  area keys: {sorted(area.keys()) if area else []}")
    if axis:
        for key in ("frontBack", "upDown", "leftRight"):
            if key in axis:
                print_vector_block(f"area.axis.{key}", axis.get(key))
    if area.get("center") is not None:
        print_vector_block("area.center", area.get("center"))

    block = find_grid_block(grid, drill.device_id)
    block_world_pos = block_value(block, "world_pos", "worldPos", "worldPosition")
    block_orientation = as_dict(block_value(block, "orientation", "Orientation"))
    block_local_orientation = as_dict(block_value(block, "local_orientation", "localOrientation", "LocalOrientation"))

    print("\nGrid block transform telemetry:")
    print_vector_block("block.world_pos", block_world_pos)
    print(f"  block.local_orientation: {compact(block_local_orientation)}")
    print(f"  block.orientation keys: {sorted(block_orientation.keys()) if block_orientation else []}")
    if block_orientation:
        for key in ("forward", "backward", "up", "down", "left", "right"):
            if key in block_orientation:
                print_vector_block(f"block.orientation.{key}", block_orientation.get(key))

    device_ok = bool(telemetry.get("position") and (axis or orientation))
    grid_block_ok = bool(block_world_pos and block_orientation)
    ok = device_ok or grid_block_ok
    print("\nTransform telemetry status:")
    if device_ok:
        print("  OK: Nanobot device transform telemetry is present.")
    elif grid_block_ok:
        print("  OK: grid block transform telemetry is present. Mining scripts can calculate AreaOffset from blocks[].orientation.")
    else:
        print("  ERROR: transform telemetry is missing.")
        print("  Update DedicatedPlugin so either Nanobot device telemetry contains position/orientation/area.axis, or grid blocks contain world_pos/orientation.")
        print("  Mining scripts will correctly stop instead of using the unsafe legacy fixed axis map.")

    print("\nPatch/property markers:")
    printed = False
    for key in sorted(props):
        low = key.lower()
        if "strict" in low or "patch" in low or "version" in low or "area" in low:
            print(f"  {key}: {compact(props.get(key), 300)}")
            printed = True
    if not printed:
        print("  <no patch/version/area properties found in properties>")

    print("\nRaw mode/filters:")
    for key in (
        "OnOff",
        "Drill.WorkMode",
        "Drill.ScriptControlled",
        "Drill.CurrentDrillTarget",
        "Drill.DrillPriorityList",
        "Drill.ComponentClassList",
    ):
        print(f"  {key}: {compact(props.get(key), 500)}")

    targets = telemetry.get("drill_possibledrilltargets", []) or []
    print(f"\nPossibleDrillTargets: {len(targets)}")
    for index, target in enumerate(targets[:20]):
        print(f"  #{index:02d}: {target}")

    print("\nTelemetry top-level keys:")
    print("  " + ", ".join(sorted(str(k) for k in telemetry.keys())))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
