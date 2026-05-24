#!/usr/bin/env python3
"""
mine_until.py — ставит AreaOffset, запускает бур, мониторит до target amount.

Usage:
    python mine_until.py --grid skynet-baza0 --ore Nickel --target X Y Z --amount 5000
    python mine_until.py --grid skynet-baza0 --ore Nickel --target X Y Z --amount 5000 --mode Drill
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
from secontrol.devices.remote_control_device import RemoteControlDevice


def get_ore_amount(grid, ore_subtype: str) -> float:
    total = 0.0
    for item in grid.get_all_grid_items():
        subtype = item.get("item_subtype", "")
        display = item.get("display_name", "")
        if ore_subtype.lower() in subtype.lower() or ore_subtype.lower() in display.lower():
            total += item.get("amount", 0)
    return total


def get_item_amount(grid, item_subtype: str) -> float:
    total = 0.0
    wanted = item_subtype.lower()
    for item in grid.get_all_grid_items():
        subtype = str(item.get("item_subtype", ""))
        display = str(item.get("display_name", ""))
        if subtype.lower() == wanted or display.lower() == wanted:
            total += item.get("amount", 0)
    return total


def parse_priority_entry(entry):
    parts = str(entry or "").split(";")
    if not parts:
        return None
    try:
        key = int(parts[0].strip())
    except ValueError:
        return None
    enabled = True
    if len(parts) >= 2:
        enabled = parts[1].strip().lower() in {"true", "1", "yes", "on"}
    return key, enabled


def wait_for_nanodrill_filters(drill, ore_subtype: str, timeout: float = 20.0) -> bool:
    wanted = ore_subtype.strip().lower()
    deadline = time.time() + timeout
    last_status = {}

    while time.time() < deadline:
        drill.wait_for_telemetry(timeout=2.0, wait_for_new=True, need_update=True)
        status = drill.debug_status()
        last_status = status

        enabled_ores = {
            str(name).lower(): bool(enabled)
            for name, enabled in (status.get("enabledKnownOres") or {}).items()
        }
        ore_ok = enabled_ores.get(wanted) is True and all(
            name == wanted or not enabled
            for name, enabled in enabled_ores.items()
        )

        collect_entries = drill.debug_get_collect_priority_list_raw()
        parsed_collect = [
            parsed for parsed in (parse_priority_entry(e) for e in collect_entries)
            if parsed is not None
        ]
        if parsed_collect:
            collect_ok = all(
                (key == 3 and enabled) or (key != 3 and not enabled)
                for key, enabled in parsed_collect
                if key in {2, 3, 4, 5}
            )
        else:
            collect_ok = drill.debug_get_resource_filter_indices() == [2]

        if ore_ok and collect_ok:
            print(f"Filters confirmed: only {ore_subtype}, collect=Ore")
            return True

        time.sleep(0.5)

    print("ERROR: filters were not confirmed by telemetry")
    print(f"Last filter status: {last_status}")
    return False


def target_mentions_ore(target, ore_subtype: str) -> bool:
    mined = target_mined_ore(target)
    if mined:
        return ore_subtype.lower() == mined.lower()

    return ore_subtype.lower() in str(target).lower()


def target_mined_ore(target) -> str:
    material = None
    if isinstance(target, dict):
        material = target.get("material") or target.get("materialDef")
    elif isinstance(target, (list, tuple)) and len(target) >= 4:
        material = target[3]

    if isinstance(material, dict):
        return str(material.get("minedOre") or material.get("mined_ore") or "").strip()

    return ""


def current_mentions_ore(current, targets, ore_subtype: str) -> bool:
    current_text = str(current)
    for target in targets:
        if isinstance(target, (list, tuple)) and target:
            if str(target[0]) == current_text:
                return target_mentions_ore(target, ore_subtype)
        elif isinstance(target, dict):
            text = target.get("target") or target.get("text") or target.get("current")
            if text is not None and str(text) == current_text:
                return target_mentions_ore(target, ore_subtype)

    return target_mentions_ore(current, ore_subtype)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine ore until target amount is reached")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--ore", default="Nickel", help="Ore type (e.g. Nickel, Gold, Uranium)")
    parser.add_argument("--target", nargs=3, type=float, metavar=("X", "Y", "Z"), required=True,
                        help="Target world coords")
    parser.add_argument("--amount", type=float, required=True, help="Target amount")
    parser.add_argument("--mode", default="Collect", choices=["Collect", "Drill", "Fill"],
                        help="Work mode (default: Collect)")
    parser.add_argument("--check-interval", type=int, default=5, help="Check interval in seconds")
    parser.add_argument("--allow-stone", action="store_true",
                        help="Keep running even if Stone is detected")
    args = parser.parse_args()

    grid = Grid.from_name(args.grid)
    print(f"Grid: {grid.name} (id={grid.grid_id})")

    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("ERROR: No Nanobot Drill found")
        return 1
    drill = drills[0]
    print(f"Drill: {drill.name} (id={drill.device_id})")

    rc_devices = grid.find_devices_by_type(RemoteControlDevice)
    rc = rc_devices[0] if rc_devices else None
    if not rc:
        print("ERROR: No Remote Control found")
        return 1
    print(f"RC: {rc.name} (id={rc.device_id})")

    baseline = get_ore_amount(grid, args.ore)
    stone_baseline = get_item_amount(grid, "Stone")
    print(f"Baseline {args.ore}: {baseline:.1f}")
    print(f"Baseline Stone: {stone_baseline:.1f}")
    print(f"Target: {args.amount:.1f}")
    print()

    # ---- Сброс ----
    drill.set_raw_property("OnOff", False)
    drill.set_raw_property("Drill.ShowArea", False)
    time.sleep(0.3)

    # ---- Настройка фильтров (ДО AreaOffset — WorkMode сбрасывает AreaOffset) ----
    print("Configuring filters...")
    drill.set_raw_property("Drill.ScriptControlled", True)
    time.sleep(0.2)
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

    # ---- Set area offset (после WorkMode — чтобы не сбросился) ----
    if not wait_for_nanodrill_filters(drill, args.ore):
        drill.set_raw_property("Drill.ShowArea", False)
        drill.set_raw_property("OnOff", False)
        return 3

    target = tuple(args.target)
    print(f"Setting area offset to target {target}...")

    rc.update()
    time.sleep(0.3)
    rc.update()
    tel = rc.telemetry or {}
    rc_pos = tel.get("position", {})
    orient = tel.get("orientation", {})
    if not rc_pos or not orient:
        print("ERROR: No RC telemetry")
        return 1

    fwd = orient["forward"]
    up = orient["up"]
    left_data = orient.get("left") or {}
    right_data = orient.get("right") or {}
    if left_data:
        lx, ly, lz = left_data["x"], left_data["y"], left_data["z"]
    elif right_data:
        lx, ly, lz = -right_data["x"], -right_data["y"], -right_data["z"]
    else:
        lx = -(fwd["y"] * up["z"] - fwd["z"] * up["y"])
        ly = -(fwd["z"] * up["x"] - fwd["x"] * up["z"])
        lz = -(fwd["x"] * up["y"] - fwd["y"] * up["x"])

    drill_local = (-2.5, 2.5, 5.0)
    rc_block = grid.blocks.get(int(rc.device_id)) if str(rc.device_id).isdigit() else None
    drill_block = grid.blocks.get(int(drill.device_id)) if str(drill.device_id).isdigit() else None
    if rc_block and drill_block and rc_block.local_position and drill_block.local_position:
        drill_local = tuple(
            drill_block.local_position[i] - rc_block.local_position[i]
            for i in range(3)
        )
        print(f"Drill local offset from metadata: {drill_local}")
    else:
        print(f"Drill local offset fallback: {drill_local}")

    drill_world = {
        "x": rc_pos["x"] + drill_local[0] * lx + drill_local[1] * up["x"] + drill_local[2] * fwd["x"],
        "y": rc_pos["y"] + drill_local[0] * ly + drill_local[1] * up["y"] + drill_local[2] * fwd["y"],
        "z": rc_pos["z"] + drill_local[0] * lz + drill_local[1] * up["z"] + drill_local[2] * fwd["z"],
    }

    import math
    ddx = target[0] - drill_world["x"]
    ddy = target[1] - drill_world["y"]
    ddz = target[2] - drill_world["z"]

    local_fwd = ddx * fwd["x"] + ddy * fwd["y"] + ddz * fwd["z"]
    local_up = ddx * up["x"] + ddy * up["y"] + ddz * up["z"]
    local_left = ddx * lx + ddy * ly + ddz * lz

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

    # ---- Включение ----
    drill.set_raw_property("Drill.ShowArea", True)
    drill.set_raw_property("OnOff", True)
    time.sleep(10)

    drill.update()
    tel = drill.telemetry or {}
    props = tel.get("properties", {})
    current = props.get("Drill.CurrentDrillTarget")

    targets = tel.get("drill_possibledrilltargets", [])
    ore_targets = [t for t in targets if target_mentions_ore(t, args.ore)]

    print(f"OnOff: {props.get('OnOff')}")
    print(f"WorkMode: {drill.get_work_mode()}")
    print(f"ShowArea: {props.get('Drill.ShowArea')}")
    print(f"ScriptControlled: {props.get('Drill.ScriptControlled')}")
    print(f"Targets: {len(targets)}, {args.ore}: {len(ore_targets)}")
    print(f"Current: {current}")

    if len(targets) == 0:
        print("WARNING: 0 targets — drill sees no ore. Run this script again to re-trigger scan.")
    if current is None:
        print("WARNING: drill not started — try running again to re-trigger")

    if not args.allow_stone:
        current_is_wrong = current is not None and not current_mentions_ore(current, targets, args.ore)
        no_requested_targets = len(targets) > 0 and not ore_targets
        if current_is_wrong or no_requested_targets:
            print()
            print("SAFETY STOP: drill target does not match requested ore.")
            print(f"Requested: {args.ore}")
            print(f"Current: {current}")
            print("Stopping drill to avoid collecting Stone. Use --allow-stone to override.")
            drill.set_raw_property("Drill.ShowArea", False)
            drill.set_raw_property("OnOff", False)
            return 2

    # ---- Monitoring loop ----
    print(f"\nMining {args.ore} until {args.amount:.1f} units...")
    if args.allow_stone:
        print("NOTE: --allow-stone set; Stone will not stop the script.")
    else:
        print("Stone safety: enabled. Drill stops if Stone increases.")
    start = time.time()
    while True:
        time.sleep(args.check_interval)
        current_amount = get_ore_amount(grid, args.ore)
        stone_amount = get_item_amount(grid, "Stone")
        elapsed = time.time() - start
        mined = current_amount - baseline
        stone_delta = stone_amount - stone_baseline
        rate = mined / elapsed if elapsed > 0 else 0
        remaining = args.amount - mined
        eta = remaining / rate if rate > 0 else float("inf")

        print(f"  [{elapsed:.0f}s] {args.ore}: {current_amount:.1f} / {args.amount:.1f} "
              f"(+{mined:.1f}, Stone +{stone_delta:.1f}, rate={rate:.1f}/s, eta={eta:.0f}s)")

        if not args.allow_stone and stone_delta > 1.0:
            print()
            print("SAFETY STOP: Stone increased.")
            print(f"Stone delta: +{stone_delta:.1f}; {args.ore} delta: +{mined:.1f}")
            break

        if mined >= args.amount:
            print(f"\nTarget reached! Delta={mined:.1f} >= {args.amount:.1f}")
            break

    print("Stopping drill...")
    drill.set_raw_property("Drill.ShowArea", False)
    drill.set_raw_property("OnOff", False)

    final = get_ore_amount(grid, args.ore)
    print(f"Final {args.ore}: {final:.1f} (+{final - baseline:.1f} from baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
