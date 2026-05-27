#!/usr/bin/env python3
"""Configure Nanobot Drill to Collect only one ore class safely.

Default example:
  python examples/organized/drill_nano/configure_ore_only.py --grid skynet-baza1 --ore Platinum
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

WORK_MODE_VALUES = {"Drill": 1, "Collect": 2, "Fill": 4}

ORE_HASHES: Dict[int, str] = {
    1137917536: "stone",
    1579040667: "ice",
    2112235764: "iron",
    -723128632: "nickel",
    -122448462: "silicon",
    -2115209756: "cobalt",
    2104309205: "magnesium",
    1033257407: "silver",
    -496794321: "gold",
    -510410391: "platinum",
    1880922462: "uranium",
}

KNOWN_ORES = {name.lower(): name.capitalize() for name in ORE_HASHES.values()}
RESOURCE_CLASSES = {1: "unknown", 2: "Ingot", 3: "Ore", 4: "Stone", 5: "Gravel"}


def parse_entry(entry: Any) -> Optional[Tuple[int, bool]]:
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


def print_filters(drill: NanobotDrillSystemDevice) -> None:
    drill.update()
    props = (drill.telemetry or {}).get("properties", {})
    print("OnOff:", props.get("OnOff"))
    print("WorkMode raw:", props.get("Drill.WorkMode"))
    print("WorkMode:", drill.get_work_mode())
    print("ScriptControlled:", props.get("Drill.ScriptControlled"))
    print("ShowArea:", props.get("Drill.ShowArea"))
    print("Current:", props.get("Drill.CurrentDrillTarget"))

    print("\nRaw DrillPriorityList:")
    for entry in drill.debug_get_priority_list_raw():
        parsed = parse_entry(entry)
        name = ORE_HASHES.get(parsed[0], "unknown") if parsed else "unknown"
        print(f"  {entry} -> {name}")

    print("\nRaw ComponentClassList:")
    for entry in drill.debug_get_collect_priority_list_raw():
        parsed = parse_entry(entry)
        name = RESOURCE_CLASSES.get(parsed[0], "unknown") if parsed else "unknown"
        print(f"  {entry} -> {name}")


def raw_filter_ok(drill: NanobotDrillSystemDevice, ore_subtype: str) -> bool:
    wanted = ore_subtype.strip().lower()
    ore_state: Dict[str, bool] = {}
    for entry in drill.debug_get_priority_list_raw():
        parsed = parse_entry(entry)
        if parsed is None:
            continue
        ore_hash, enabled = parsed
        name = ORE_HASHES.get(ore_hash)
        if name:
            ore_state[name] = enabled

    resource_state: Dict[str, bool] = {}
    for entry in drill.debug_get_collect_priority_list_raw():
        parsed = parse_entry(entry)
        if parsed is None:
            continue
        key, enabled = parsed
        name = RESOURCE_CLASSES.get(key)
        if name:
            resource_state[name.lower()] = enabled

    ore_ok = ore_state.get(wanted) is True and all(
        name == wanted or not enabled for name, enabled in ore_state.items()
    )
    resource_ok = resource_state.get("ore") is True and all(
        name == "ore" or not enabled for name, enabled in resource_state.items()
    )
    return ore_ok and resource_ok


def wait_until_only_ore(drill: NanobotDrillSystemDevice, ore_subtype: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        drill.wait_for_telemetry(timeout=2.0, wait_for_new=True, need_update=True)
        if raw_filter_ok(drill, ore_subtype):
            return True
        time.sleep(0.5)
    return False


def safe_action(drill: NanobotDrillSystemDevice, action_id: str) -> None:
    try:
        drill.run_action(action_id)
    except Exception as exc:
        print(f"WARNING: action {action_id} failed: {exc}")


def safe_set(drill: NanobotDrillSystemDevice, property_name: str, value: Any) -> None:
    try:
        drill.set_raw_property(property_name, value)
    except Exception as exc:
        print(f"WARNING: set {property_name}={value!r} failed: {exc}")


def find_drill(grid: Grid, name_filter: str | None) -> NanobotDrillSystemDevice:
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        raise RuntimeError("Nanobot Drill not found")
    if not name_filter:
        return drills[0]
    wanted = name_filter.lower()
    for drill in drills:
        if wanted in drill.name.lower():
            return drill
    names = ", ".join(drill.name for drill in drills)
    raise RuntimeError(f"No Nanobot Drill name contains {name_filter!r}. Available: {names}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure strict one-ore Nanobot Collect mode")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--ore", default="Platinum", help="Ore name, default: Platinum")
    parser.add_argument("--drill-name", default=None, help="Optional Nanobot Drill name substring")
    parser.add_argument("--timeout", type=float, default=20.0, help="Filter confirmation timeout")
    parser.add_argument("--use-conveyor", action="store_true", default=True, help="Keep conveyor enabled")
    parser.add_argument("--no-conveyor", action="store_true", help="Disable conveyor after configuring")
    args = parser.parse_args()

    key = args.ore.strip().lower()
    if key not in KNOWN_ORES:
        print(f"ERROR: unknown ore {args.ore!r}. Known ores: {', '.join(sorted(KNOWN_ORES))}")
        return 1
    ore = KNOWN_ORES[key]

    grid = Grid.from_name(args.grid)
    drill = find_drill(grid, args.drill_name)

    print(f"Grid: {grid.name} (id={grid.grid_id})")
    print(f"Drill: {drill.name} (id={drill.device_id})")
    print("\nBefore:")
    print_filters(drill)
    print(f"\nConfiguring strict {ore}-only Collect mode...")

    safe_set(drill, "OnOff", False)
    time.sleep(0.2)
    safe_set(drill, "Drill.ShowArea", False)
    time.sleep(0.2)

    for action in ("CollectIfIdle_Off", "TerrainClearingMode_Off"):
        safe_action(drill, action)
        time.sleep(0.15)

    conveyor = bool(args.use_conveyor and not args.no_conveyor)
    for prop, value in (
        ("Drill.CollectIfIdle", False),
        ("Drill.TerrainClearingMode", False),
        ("DrillSystem.CollectIfIdle", False),
        ("DrillSystem.TerrainClearingMode", False),
        ("UseConveyor", conveyor),
        ("Drill.UseConveyor", conveyor),
        ("DrillSystem.UseConveyor", conveyor),
    ):
        safe_set(drill, prop, value)
        time.sleep(0.1)

    safe_set(drill, "Drill.ScriptControlled", True)
    time.sleep(0.3)

    try:
        drill.clear_collect_filter()
        time.sleep(0.3)
    except Exception as exc:
        print("WARNING: clear_collect_filter failed:", exc)

    try:
        drill.clear_ore_filters(work_mode="Collect")
        time.sleep(0.3)
    except Exception as exc:
        print("WARNING: clear_ore_filters failed:", exc)

    drill.set_collect_filter(["Ore"])
    time.sleep(0.3)
    drill.set_ore_filters([ore], work_mode="Collect")
    time.sleep(0.3)

    safe_set(drill, "Drill.WorkMode", WORK_MODE_VALUES["Collect"])
    time.sleep(0.3)
    safe_set(drill, "Drill.ScriptControlled", False)
    time.sleep(0.3)
    try:
        drill.set_script_controlled_action(False)
        time.sleep(0.3)
    except Exception as exc:
        print("WARNING: ScriptControlled_Off action failed:", exc)

    safe_set(drill, "Drill.WorkMode", WORK_MODE_VALUES["Collect"])
    time.sleep(0.5)

    if not wait_until_only_ore(drill, ore, timeout=args.timeout):
        print("\nERROR: filters were not confirmed")
        print_filters(drill)
        return 2

    print("\nAfter:")
    print_filters(drill)
    print(f"\nOK: configured {ore}-only filter. Drill is still OFF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
