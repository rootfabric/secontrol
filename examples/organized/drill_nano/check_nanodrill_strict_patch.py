#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Nanobot strict patch version and raw filters")
    parser.add_argument("--grid", default="skynet-baza1")
    parser.add_argument("--drill-name", default=None)
    args = parser.parse_args()

    grid = Grid.from_name(args.grid)
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if args.drill_name:
        drills = [d for d in drills if args.drill_name.lower() in d.name.lower()]
    if not drills:
        print("ERROR: Nanobot Drill not found")
        return 1

    drill = drills[0]
    print(f"Grid: {grid.name} ({grid.grid_id})")
    print(f"Drill: {drill.name} ({drill.device_id})")

    for _ in range(2):
        drill.update()
        time.sleep(0.5)

    tel = drill.telemetry or {}
    props = tel.get("properties", {}) if isinstance(tel.get("properties"), dict) else {}

    print("\nPatch markers/properties:")
    for key in sorted(props):
        if "strict" in key.lower() or "patch" in key.lower() or "version" in key.lower():
            print(f"  {key}: {props.get(key)}")

    print("\nDetailedInfo snippets:")
    for key in ("detailedInfo", "rawDetailedInfo", "customInfo"):
        value = tel.get(key)
        if value:
            text = str(value)
            found = [line for line in text.splitlines() if "strict" in line.lower() or "patch" in line.lower()]
            print(f"  {key}:")
            if found:
                for line in found:
                    print("    " + line)
            else:
                print("    <no strict/patch lines>")

    print("\nRaw mode/filters:")
    for key in (
        "OnOff",
        "Drill.WorkMode",
        "Drill.ScriptControlled",
        "Drill.CurrentDrillTarget",
        "Drill.StrictPatchVersion",
        "Drill.DrillPriorityList",
        "Drill.ComponentClassList",
    ):
        print(f"  {key}: {props.get(key)}")

    targets = tel.get("drill_possibledrilltargets", []) or []
    print(f"\nPossibleDrillTargets: {len(targets)}")
    for i, target in enumerate(targets[:20]):
        print(f"  #{i:02d}: {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
