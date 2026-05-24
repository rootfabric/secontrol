#!/usr/bin/env python3
"""
stop_drill.py — Останавливает бур, выключает подсветку и HUD.

Usage:
    python stop_drill.py --grid skynet-baza0
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop Nanobot Drill")
    parser.add_argument("--grid", required=True, help="Grid name")
    args = parser.parse_args()

    grid = Grid.from_name(args.grid)
    print(f"Grid: {grid.name} (id={grid.grid_id})")

    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("ERROR: No Nanobot Drill found")
        return 1

    drill = drills[0]
    print(f"Drill: {drill.name} (id={drill.device_id})")

    drill.set_raw_property("ShowOnHUD", False)
    time.sleep(0.1)
    drill.set_raw_property("Drill.ShowArea", False)
    time.sleep(0.1)
    drill.set_raw_property("OnOff", False)
    time.sleep(0.3)

    drill.update()
    props = drill.telemetry.get("properties", {})
    print(f"OnOff: {props.get('OnOff')}")
    print(f"ShowArea: {props.get('Drill.ShowArea')}")
    print(f"ShowOnHUD: {props.get('ShowOnHUD')}")
    print("Drill stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
