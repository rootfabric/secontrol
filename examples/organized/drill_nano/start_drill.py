#!/usr/bin/env python3
"""
start_drill.py — Включает бур, подсвечивает область, триггерит рескан, добывает.

Usage:
    python start_drill.py --grid skynet-baza0 --ore Nickel
    python start_drill.py --grid skynet-baza0 --ore Gold --mode Collect
    python start_drill.py --grid skynet-baza0 --target -50625.8 146646.9 -137740.2
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


def get_grid_left_axis(orient: dict) -> tuple:
    left = orient.get("left")
    if left:
        return left["x"], left["y"], left["z"]
    right = orient.get("right")
    if right:
        return -right["x"], -right["y"], -right["z"]
    fwd = orient["forward"]
    up = orient["up"]
    return - (fwd["y"] * up["z"] - fwd["z"] * up["y"]), - (fwd["z"] * up["x"] - fwd["x"] * up["z"]), - (fwd["x"] * up["y"] - fwd["y"] * up["x"])


def set_area_offset(drill, rc, target: tuple) -> None:
    rc.update()
    time.sleep(0.3)
    rc.update()
    tel = rc.telemetry or {}
    rc_pos = tel.get("position", {})
    orient = tel.get("orientation", {})
    if not rc_pos or not orient:
        print("WARNING: No RC telemetry, skipping area offset")
        return

    fwd = orient["forward"]
    up = orient["up"]
    lx, ly, lz = get_grid_left_axis(orient)

    # Drill local offset from RC (based on skynet-baza0 layout)
    drill_local = (-2.5, 2.5, 5.0)

    drill_world = {
        "x": rc_pos["x"] + drill_local[0] * lx + drill_local[1] * up["x"] + drill_local[2] * fwd["x"],
        "y": rc_pos["y"] + drill_local[0] * ly + drill_local[1] * up["y"] + drill_local[2] * fwd["y"],
        "z": rc_pos["z"] + drill_local[0] * lz + drill_local[1] * up["z"] + drill_local[2] * fwd["z"],
    }

    ddx = target[0] - drill_world["x"]
    ddy = target[1] - drill_world["y"]
    ddz = target[2] - drill_world["z"]

    local_fwd = ddx * fwd["x"] + ddy * fwd["y"] + ddz * fwd["z"]
    local_up = ddx * up["x"] + ddy * up["y"] + ddz * up["z"]
    local_left = ddx * lx + ddy * ly + ddz * lz

    # DRILL_AXIS_MAP for skynet-baza0: LeftRight=(0,1), UpDown=(2,1), FrontBack=(1,1)
    grid_vec = [local_left, local_up, local_fwd]
    drill_fb = grid_vec[1] * 1
    drill_ud = grid_vec[2] * 1
    drill_lr = grid_vec[0] * 1

    print(f"Area offset: FB={drill_fb:.1f} UD={drill_ud:.1f} LR={drill_lr:.1f}")
    print(f"Drill to target: {math.sqrt(ddx**2 + ddy**2 + ddz**2):.1f}m")

    drill.set_raw_property("Drill.AreaOffsetFrontBack", round(drill_fb, 1))
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetUpDown", round(drill_ud, 1))
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetLeftRight", round(drill_lr, 1))
    time.sleep(0.1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Nanobot Drill mining")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--ore", default="Nickel", help="Ore type (default: Nickel)")
    parser.add_argument("--mode", default="Collect", choices=["Collect", "Drill", "Fill"], help="Work mode")
    parser.add_argument("--target", nargs=3, type=float, metavar=("X", "Y", "Z"), help="Target world coords")
    args = parser.parse_args()

    grid = Grid.from_name(args.grid)
    print(f"Grid: {grid.name} (id={grid.grid_id})")

    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("ERROR: No Nanobot Drill found")
        return 1

    drill = drills[0]
    print(f"Drill: {drill.name} (id={drill.device_id})")
    print(f"Mining: {args.ore}, mode: {args.mode}")

    # Сброс
    drill.set_raw_property("OnOff", False)
    drill.set_raw_property("Drill.ShowArea", False)
    time.sleep(0.3)

    # Настройка фильтров (паттерн из simple_nano_drill.py)
    drill.set_raw_property("Drill.ScriptControlled", True)
    time.sleep(0.2)
    drill.set_raw_property("Drill.CollectFilter", "Ore")
    time.sleep(0.1)
    drill.set_collect_filter(["Ore"])
    time.sleep(0.2)
    drill.set_ore_filters([args.ore], work_mode=args.mode)
    time.sleep(0.2)
    drill.set_raw_property("Drill.WorkMode", {"Collect": 1, "Drill": 2, "Fill": 0}[args.mode])
    time.sleep(0.2)
    drill.set_raw_property("Drill.ScriptControlled", False)
    time.sleep(0.2)
    drill.set_raw_property("Drill.WorkMode", {"Collect": 1, "Drill": 2, "Fill": 0}[args.mode])
    time.sleep(0.2)

    # Установка area offset (если указан target) или перезапись текущего (триггер рескана)
    if args.target:
        rc_devices = grid.find_devices_by_type(RemoteControlDevice)
        rc = rc_devices[0] if rc_devices else None
        if rc:
            set_area_offset(drill, rc, tuple(args.target))
        else:
            print("WARNING: No RC, setting offset directly")
            drill.set_raw_property("Drill.AreaOffsetFrontBack", args.target[0])
            drill.set_raw_property("Drill.AreaOffsetUpDown", args.target[1])
            drill.set_raw_property("Drill.AreaOffsetLeftRight", args.target[2])
    else:
        # Перезаписать текущие оффсеты — триггернуть рескан
        drill.update()
        props = drill.telemetry.get("properties", {})
        for prop in ("Drill.AreaOffsetFrontBack", "Drill.AreaOffsetUpDown", "Drill.AreaOffsetLeftRight"):
            val = props.get(prop)
            if val is not None:
                drill.set_raw_property(prop, val)
                time.sleep(0.1)

    # Подсветка области + включение
    drill.set_raw_property("Drill.ShowArea", True)
    drill.set_raw_property("OnOff", True)
    # Моду нужно ~10s на авто-запуск (Collect + ScriptControlled=False)
    time.sleep(10)
    drill.update()
    tel = drill.telemetry or {}
    props = tel.get("properties", {})
    current = props.get("Drill.CurrentDrillTarget")

    targets = tel.get("drill_possibledrilltargets", [])
    nickel = [t for t in targets if args.ore in str(t)]

    print()
    print(f"OnOff: {props.get('OnOff')}")
    print(f"WorkMode: {drill.get_work_mode()}")
    print(f"ShowArea: {props.get('Drill.ShowArea')}")
    print(f"ScriptControlled: {props.get('Drill.ScriptControlled')}")
    print(f"Enabled: {drill.debug_get_enabled_known_ores()}")
    print(f"Targets: {len(targets)}, {args.ore}: {len(nickel)}")
    print(f"Current: {current}")
    if current is None:
        print("WARNING: drill not started — try running again to re-trigger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
