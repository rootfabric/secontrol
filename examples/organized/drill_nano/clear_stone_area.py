#!/usr/bin/env python3
"""Clear Stone in the Nanobot Drill area.

Designed for Outenemy Nanobot Drill System - Automation Fixes.

Default behavior:
  - configure Nanobot in Drill mode;
  - enable only Stone material and Stone collect class, because strict v12 filtering
    requires both lists to allow the material;
  - disable conveyor and background collect modes;
  - optionally aim the area at a world target;
  - clear Stone for a fixed time or until Stone targets disappear;
  - stop the drill;
  - restore safe Collect mode for Platinum by default.

Examples:
  python examples/organized/drill_nano/clear_stone_area.py ^
    --grid skynet-baza1 ^
    --target -56796.387 146498.057 -134204.677 ^
    --area-size 15 ^
    --seconds 30

  python examples/organized/drill_nano/clear_stone_area.py ^
    --grid skynet-baza1 ^
    --use-current-area ^
    --seconds 20 ^
    --no-restore
"""

from __future__ import annotations

import argparse
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
    configure_collect_mode,
    force_work_mode,
    format_point,
    get_item_amount,
    get_navigation_frame,
    get_ore_amount,
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
DEFAULT_CLEAR_MATERIAL = "Stone"
DEFAULT_RESTORE_ORE = "Platinum"

KNOWN_MATERIALS = {
    "stone",
    "ice",
    "iron",
    "nickel",
    "silicon",
    "cobalt",
    "magnesium",
    "silver",
    "gold",
    "platinum",
    "uranium",
}


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
    raise RuntimeError(f"No Nanobot Drill name contains '{name_filter}'. Available: {available}")


def find_remote_control(grid: Grid) -> RemoteControlDevice:
    devices = grid.find_devices_by_type(RemoteControlDevice)
    if not devices:
        raise RuntimeError("No Remote Control found on grid")
    return devices[0]


def get_props(drill: NanobotDrillSystemDevice) -> Dict[str, Any]:
    drill.update()
    props = (drill.telemetry or {}).get("properties", {})
    return props if isinstance(props, dict) else {}


def amount_for_material(grid: Grid, material: str) -> float:
    if material.strip().lower() == "stone":
        return get_item_amount(grid, "Stone")
    return get_ore_amount(grid, material)


def material_targets(targets: List[Any], material: str) -> List[Any]:
    return [target for target in targets if target_has_ore(target, material)]


def dump_targets(targets: List[Any], material: str, limit: int) -> None:
    shown = min(limit, len(targets))
    if shown <= 0:
        return
    print(f"Targets dump, first {shown}/{len(targets)}:")
    for index, target in enumerate(targets[:shown]):
        mark = "<-- clear material" if target_has_ore(target, material) else ""
        print(f"  target #{index:02d}: {target} {mark}")


def set_area_size(drill: NanobotDrillSystemDevice, area_size: float) -> None:
    if area_size <= 0:
        return
    for property_name in ("Drill.AreaWidth", "Drill.AreaHeight", "Drill.AreaDepth"):
        safe_set_raw(drill, property_name, float(area_size))
        time.sleep(0.08)


def configure_clear_material_mode(
    drill: NanobotDrillSystemDevice,
    material: str,
    filter_delay: float,
    try_destroy_material: bool,
) -> None:
    """Configure Nanobot to remove one voxel material from the area.

    Strict Automation Fix v12 checks both DrillPriorityList and ComponentClassList.
    For Stone clearing we therefore intentionally enable both:
      - material filter: Stone=True;
      - collect class filter: Stone=True.

    Conveyor stays disabled so Stone should not be pushed to ship containers.
    If a future mod build exposes Drill.DestroyMinedMaterial, the script enables it.
    """
    print(f"Configuring clear mode for material: {material}")

    stop_drill(drill, hide_area=True)
    time.sleep(0.4)

    for action_id in (
        "CollectIfIdle_Off",
        "TerrainClearingMode_Off",
    ):
        safe_action(drill, action_id)
        time.sleep(0.08)

    for property_name, value in (
        ("UseConveyor", False),
        ("Drill.UseConveyor", False),
        ("DrillSystem.UseConveyor", False),
        ("Drill.CollectIfIdle", False),
        ("Drill.TerrainClearingMode", False),
        ("DrillSystem.CollectIfIdle", False),
        ("DrillSystem.TerrainClearingMode", False),
    ):
        safe_set_raw(drill, property_name, value)
        time.sleep(0.06)

    if try_destroy_material:
        # Present only in experimental destroy builds. Safe to try; ignored if absent.
        safe_set_raw(drill, "Drill.DestroyMinedMaterial", True)
        safe_action(drill, "DestroyMinedMaterial_On")
        time.sleep(0.15)

    safe_set_raw(drill, "Drill.ScriptControlled", True)
    time.sleep(0.3)

    # v12 strict filtering needs ComponentClass Stone=True for Stone targets to exist.
    send_collect_filter_direct(drill, ["Stone"])
    time.sleep(filter_delay)

    send_ore_filter_direct(
        drill,
        [material],
        work_mode_value=WORK_MODE_VALUES["Drill"],
        apply_collect_filter=False,
    )
    time.sleep(filter_delay)

    force_work_mode(drill, WORK_MODE_VALUES["Drill"], delay=0.3)

    safe_set_raw(drill, "Drill.ScriptControlled", False)
    time.sleep(0.3)
    try:
        drill.set_script_controlled_action(False)
    except Exception as exc:
        print(f"WARNING: ScriptControlled_Off failed: {exc}")
    time.sleep(0.2)

    force_work_mode(drill, WORK_MODE_VALUES["Drill"], delay=0.3)

    if try_destroy_material:
        safe_set_raw(drill, "Drill.DestroyMinedMaterial", True)
        time.sleep(0.1)


def restore_safe_collect(
    drill: NanobotDrillSystemDevice,
    restore_ore: str,
    filter_timeout: float,
    use_conveyor: bool,
) -> bool:
    restore_ore = restore_ore.strip()
    if not restore_ore:
        return True

    print(f"Restoring safe Collect mode: Ore + {restore_ore}")
    ok = configure_collect_mode(
        drill=drill,
        ore_subtype=restore_ore,
        use_conveyor=use_conveyor,
        filter_timeout=filter_timeout,
    )
    if ok:
        print("Safe Collect mode restored.")
    else:
        print("WARNING: safe Collect mode was not confirmed after clearing.")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear Stone/material in Nanobot Drill area")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--material", default=DEFAULT_CLEAR_MATERIAL, help="Material to clear, default: Stone")
    parser.add_argument("--target", nargs=3, type=float, metavar=("X", "Y", "Z"), help="World target coordinates")
    parser.add_argument("--use-current-area", action="store_true", help="Do not change AreaOffset, use current Nanobot area")
    parser.add_argument("--area-size", type=float, default=15.0, help="Area width/height/depth in meters; <=0 keeps current size")
    parser.add_argument("--seconds", type=float, default=30.0, help="Maximum clear time")
    parser.add_argument("--check-interval", type=float, default=1.0, help="Monitor interval")
    parser.add_argument("--idle-stop-seconds", type=float, default=8.0, help="Stop after this many seconds without material targets; 0 disables")
    parser.add_argument("--drill-name", default=None, help="Optional Nanobot Drill name substring")
    parser.add_argument("--target-dump", type=int, default=8, help="How many targets to print")
    parser.add_argument("--filter-delay", type=float, default=0.5, help="Delay after filter commands")
    parser.add_argument("--try-destroy-material", action="store_true", help="Try enabling experimental Drill.DestroyMinedMaterial if present")
    parser.add_argument("--restore-ore", default=DEFAULT_RESTORE_ORE, help="Restore safe Collect mode for this ore after clearing; empty disables")
    parser.add_argument("--no-restore", action="store_true", help="Do not restore Collect mode after clearing")
    parser.add_argument("--restore-no-conveyor", action="store_true", help="Keep conveyor disabled when restoring Collect mode")
    parser.add_argument("--restore-timeout", type=float, default=20.0, help="Filter confirmation timeout for restore")
    args = parser.parse_args()

    material = args.material.strip()
    if not material:
        print("ERROR: --material must not be empty")
        return 1
    if material.lower() not in KNOWN_MATERIALS:
        print(f"ERROR: unknown material '{material}'. Known: {', '.join(sorted(KNOWN_MATERIALS))}")
        return 1
    if args.seconds <= 0:
        print("ERROR: --seconds must be > 0")
        return 1
    if not args.use_current_area and args.target is None:
        print("ERROR: provide --target X Y Z or use --use-current-area")
        return 1

    grid = Grid.from_name(args.grid)
    drill = find_drill(grid, args.drill_name)

    print(f"Grid: {grid.name} (id={grid.grid_id})")
    print(f"Drill: {drill.name} (id={drill.device_id})")

    baseline_material = amount_for_material(grid, material)
    baseline_stone = get_item_amount(grid, "Stone")
    print(f"Baseline {material}: {baseline_material:.1f}")
    print(f"Baseline Stone: {baseline_stone:.1f}")

    configure_clear_material_mode(
        drill=drill,
        material=material,
        filter_delay=args.filter_delay,
        try_destroy_material=args.try_destroy_material,
    )
    print_raw_filters(drill)

    if args.use_current_area:
        print("Using current Nanobot AreaOffset.")
        set_area_size(drill, args.area_size)
    else:
        rc = find_remote_control(grid)
        print(f"RC: {rc.name} (id={rc.device_id})")
        drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)
        target: Vector = (float(args.target[0]), float(args.target[1]), float(args.target[2]))
        print(f"Target: {format_point(target)}")
        # WorkMode can reset AreaOffset, so area is set only after mode configuration.
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

    print(f"Clearing {material} for up to {args.seconds:.1f}s...")
    started = power_on_drill(
        drill,
        expected_work_mode=WORK_MODE_VALUES["Drill"],
        retries=4,
    )
    if not started:
        print("ERROR: Nanobot did not power on in Drill clear mode")
        stop_drill(drill, hide_area=False)
        return 2

    started_at = time.time()
    last_seen_target_at: Optional[float] = None

    while True:
        time.sleep(max(0.2, args.check_interval))
        elapsed = time.time() - started_at
        current, targets, props = read_targets(drill)
        clear_targets = material_targets(targets, material)
        if clear_targets or (current is not None and target_has_ore(current, material)):
            last_seen_target_at = time.time()

        material_delta = amount_for_material(grid, material) - baseline_material
        stone_delta = get_item_amount(grid, "Stone") - baseline_stone
        destroy_state = props.get("Drill.DestroyMinedMaterial")

        print(
            f"  [{elapsed:.0f}/{args.seconds:.0f}s] "
            f"targets={len(targets)}, {material}Targets={len(clear_targets)}, "
            f"inventory {material} delta={material_delta:+.1f}, Stone delta={stone_delta:+.1f}, "
            f"WorkMode={props.get('Drill.WorkMode')}, DestroyMinedMaterial={destroy_state}, current={current}"
        )

        if targets and not clear_targets and current is not None and not target_has_ore(current, material):
            print(f"SAFETY STOP: current target is not {material}: {current}")
            dump_targets(targets, material, args.target_dump)
            break

        if elapsed >= args.seconds:
            print("Max clear time reached.")
            break

        if args.idle_stop_seconds > 0 and elapsed >= args.idle_stop_seconds:
            no_target_for = time.time() - (last_seen_target_at or started_at)
            if no_target_for >= args.idle_stop_seconds:
                print(f"No {material} targets for {no_target_for:.1f}s; stopping.")
                break

    stop_drill(drill, hide_area=False)
    time.sleep(0.5)

    final_material_delta = amount_for_material(grid, material) - baseline_material
    final_stone_delta = get_item_amount(grid, "Stone") - baseline_stone
    print(f"Done. Inventory {material} delta={final_material_delta:+.1f}; Stone delta={final_stone_delta:+.1f}")

    if not args.no_restore:
        restore_ore = "" if args.restore_ore is None else args.restore_ore.strip()
        if restore_ore:
            restore_safe_collect(
                drill=drill,
                restore_ore=restore_ore,
                filter_timeout=args.restore_timeout,
                use_conveyor=not bool(args.restore_no_conveyor),
            )
        else:
            print("Restore skipped: --restore-ore is empty.")
    else:
        print("Restore skipped by --no-restore. WARNING: Stone clear filter may remain active.")

    print("Clear operation finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
