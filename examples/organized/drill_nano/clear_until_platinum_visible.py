#!/usr/bin/env python3
"""
clear_until_platinum_visible.py — вскрывает камень нанобуром и останавливается,
как только Platinum появляется в доступных целях Nanobot Drill.

Идея:
  1. Ставит маленькую рабочую зону на world target.
  2. Включает Nanobot в режиме Drill, чтобы вскрывать породу.
  3. Отключает конвейер/автосбор, чтобы не тащить камень в контейнеры.
  4. Каждые N секунд проверяет PossibleDrillTargets и CurrentDrillTarget.
  5. Как только видит Platinum — сразу выключает бур.
  6. Опционально переводит бур в безопасный режим Collect: only Platinum + Ore.

Пример:
  python examples/organized/drill_nano/clear_until_platinum_visible.py ^
    --grid skynet-baza1 ^
    --target -56801.387 146493.057 -134209.677 ^
    --area-size 3 ^
    --check-interval 1 ^
    --max-seconds 180 ^
    --target-dump 30
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


WORK_MODE_VALUES = {
    "Drill": 1,
    "Collect": 2,
    "Fill": 4,
}

ORE_HASHES: Dict[str, int] = {
    "stone": 1137917536,
    "ice": 1579040667,
    "iron": 2112235764,
    "nickel": -723128632,
    "silicon": -122448462,
    "cobalt": -2115209756,
    "magnesium": 2104309205,
    "silver": 1033257407,
    "gold": -496794321,
    "platinum": -510410391,
    "uranium": 1880922462,
}

HASH_TO_ORE = {value: key for key, value in ORE_HASHES.items()}
RESOURCE_CLASS_NAMES = {1: "unknown", 2: "Ingot", 3: "Ore", 4: "Stone", 5: "Gravel"}

# Должно совпадать с рабочим set_nanodrill_area.py для этого грида.
# Grid vector order: [Left/X, Up/Y, Forward/Z]
# Nanobot properties: [LeftRight, UpDown, FrontBack]
DRILL_AXIS_MAP = {
    "LeftRight": (0, 1),
    "UpDown": (2, 1),
    "FrontBack": (1, 1),
}


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(value or "").lower())


def parse_priority_entry(entry: Any) -> Optional[Tuple[int, bool]]:
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


def material_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, dict):
        keys = (
            "minedOre", "mined_ore", "MinedOre",
            "subtype", "SubtypeName", "subtypeName",
            "name", "Name", "type", "Type",
        )
        parts = []
        for key in keys:
            raw = value.get(key)
            if raw:
                parts.append(str(raw))
        return " ".join(parts) if parts else str(value)

    return str(value)


def target_material_text(target: Any) -> str:
    if isinstance(target, dict):
        for key in ("material", "materialDef", "currentMaterial", "CurrentMaterialDef"):
            if key in target:
                return material_text(target.get(key))
        return str(target)

    if isinstance(target, (list, tuple)) and len(target) >= 4:
        return material_text(target[3])

    return str(target)


def target_has_ore(target: Any, ore_subtype: str) -> bool:
    wanted = normalize_text(ore_subtype)
    text = normalize_text(target_material_text(target))
    return bool(wanted and wanted in text)


def current_has_ore(current: Any, targets: Iterable[Any], ore_subtype: str) -> bool:
    current_text = str(current)

    for target in targets:
        if isinstance(target, (list, tuple)) and target:
            if str(target[0]) == current_text:
                return target_has_ore(target, ore_subtype)

        if isinstance(target, dict):
            text = target.get("target") or target.get("text") or target.get("current")
            if text is not None and str(text) == current_text:
                return target_has_ore(target, ore_subtype)

    return target_has_ore(current, ore_subtype)


def target_distance(target: Any) -> Optional[float]:
    try:
        if isinstance(target, dict):
            value = target.get("distance") or target.get("Distance")
        elif isinstance(target, (list, tuple)) and len(target) >= 3:
            value = target[2]
        else:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def target_amount(target: Any) -> Optional[float]:
    try:
        if isinstance(target, dict):
            value = target.get("amount") or target.get("Amount")
        elif isinstance(target, (list, tuple)) and len(target) >= 5:
            value = target[4]
        else:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def dump_targets(targets: List[Any], ore_subtype: str, limit: int) -> None:
    print(f"Possible targets dump, first {min(limit, len(targets))}/{len(targets)}:")
    for i, target in enumerate(targets[:limit]):
        dist = target_distance(target)
        amount = target_amount(target)
        material = target_material_text(target)
        mark = "<-- requested" if target_has_ore(target, ore_subtype) else ""
        dist_text = f"dist={dist:.1f}" if dist is not None else "dist=?"
        amount_text = f"amount={amount:.1f}" if amount is not None else "amount=?"
        print(f"  #{i:02d}: {dist_text}, {amount_text}, material={material} {mark}")


def print_raw_filters(drill: NanobotDrillSystemDevice) -> None:
    print("Raw DrillPriorityList:")
    for entry in drill.debug_get_priority_list_raw():
        parsed = parse_priority_entry(entry)
        name = HASH_TO_ORE.get(parsed[0], "unknown") if parsed else "unknown"
        print(f"  {entry} -> {name}")

    print("Raw ComponentClassList:")
    for entry in drill.debug_get_collect_priority_list_raw():
        parsed = parse_priority_entry(entry)
        name = RESOURCE_CLASS_NAMES.get(parsed[0], "unknown") if parsed else "unknown"
        print(f"  {entry} -> {name}")


def get_item_amount(grid: Grid, item_subtype: str) -> float:
    total = 0.0
    wanted = item_subtype.lower()

    for item in grid.get_all_grid_items():
        subtype = str(item.get("item_subtype", ""))
        display = str(item.get("display_name", ""))
        if subtype.lower() == wanted or display.lower() == wanted:
            total += float(item.get("amount", 0) or 0)

    return total


def get_ore_amount(grid: Grid, ore_subtype: str) -> float:
    total = 0.0
    wanted = ore_subtype.lower()

    for item in grid.get_all_grid_items():
        subtype = str(item.get("item_subtype", ""))
        display = str(item.get("display_name", ""))
        if wanted in subtype.lower() or wanted in display.lower():
            total += float(item.get("amount", 0) or 0)

    return total


def vector_from_dict(data: Dict[str, Any]) -> Tuple[float, float, float]:
    return (float(data["x"]), float(data["y"]), float(data["z"]))


def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_mul(a, k: float):
    return (a[0] * k, a[1] * k, a[2] * k)


def v_dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_len(a) -> float:
    return math.sqrt(v_dot(a, a))


def v_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def drill_offsets_from_grid_vector(local_left: float, local_up: float, local_fwd: float) -> Tuple[float, float, float]:
    grid_vec = [local_left, local_up, local_fwd]

    def remap(prop_name: str) -> float:
        axis, sign = DRILL_AXIS_MAP[prop_name]
        return grid_vec[axis] * sign

    frontback = remap("FrontBack")
    updown = remap("UpDown")
    leftright = remap("LeftRight")
    return frontback, updown, leftright


def grid_vector_from_drill_offsets(frontback: float, updown: float, leftright: float) -> Tuple[float, float, float]:
    grid_vec = [0.0, 0.0, 0.0]
    for prop_name, value in (
        ("FrontBack", frontback),
        ("UpDown", updown),
        ("LeftRight", leftright),
    ):
        axis, sign = DRILL_AXIS_MAP[prop_name]
        grid_vec[axis] = value / sign
    return grid_vec[0], grid_vec[1], grid_vec[2]


def get_block_local_position(grid: Grid, device_id: int | str) -> Optional[Tuple[float, float, float]]:
    if not hasattr(grid, "blocks") or not grid.blocks:
        return None

    wanted_id = str(device_id)

    if isinstance(grid.blocks, dict):
        for block in grid.blocks.values():
            if str(getattr(block, "block_id", "")) == wanted_id:
                local_position = getattr(block, "local_position", None)
                if local_position:
                    return (
                        float(local_position[0]),
                        float(local_position[1]),
                        float(local_position[2]),
                    )

    return None


def get_drill_local_offset(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice,
) -> Optional[Tuple[float, float, float]]:
    drill_pos = get_block_local_position(grid, drill.device_id)
    rc_pos = get_block_local_position(grid, rc.device_id)

    if drill_pos is None or rc_pos is None:
        return None

    return (
        drill_pos[0] - rc_pos[0],
        drill_pos[1] - rc_pos[1],
        drill_pos[2] - rc_pos[2],
    )


def read_targets(drill: NanobotDrillSystemDevice) -> Tuple[Any, List[Any], Dict[str, Any]]:
    drill.update()
    tel = drill.telemetry or {}
    props = tel.get("properties", {})
    current = props.get("Drill.CurrentDrillTarget")
    targets = tel.get("drill_possibledrilltargets", []) or []
    return current, targets, props


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


def stop_drill(drill: NanobotDrillSystemDevice, keep_area: bool = True) -> None:
    safe_set(drill, "OnOff", False)
    time.sleep(0.1)
    if not keep_area:
        safe_set(drill, "Drill.ShowArea", False)
        time.sleep(0.1)


def configure_platinum_collect_ready(drill: NanobotDrillSystemDevice) -> None:
    print("Configuring safe Platinum collect mode after opening...")

    safe_set(drill, "OnOff", False)
    time.sleep(0.2)

    safe_set(drill, "Drill.ScriptControlled", True)
    time.sleep(0.2)

    try:
        drill.clear_collect_filter()
        time.sleep(0.2)
    except Exception as exc:
        print("WARNING: clear_collect_filter failed:", exc)

    try:
        drill.clear_ore_filters(work_mode="Collect")
        time.sleep(0.2)
    except Exception as exc:
        print("WARNING: clear_ore_filters failed:", exc)

    drill.set_collect_filter(["Ore"])
    time.sleep(0.2)
    drill.set_ore_filters(["Platinum"], work_mode="Collect")
    time.sleep(0.2)

    safe_set(drill, "Drill.WorkMode", WORK_MODE_VALUES["Collect"])
    time.sleep(0.2)

    safe_set(drill, "Drill.ScriptControlled", False)
    time.sleep(0.2)

    try:
        drill.set_script_controlled_action(False)
        time.sleep(0.2)
    except Exception as exc:
        print("WARNING: ScriptControlled_Off action failed:", exc)

    safe_set(drill, "Drill.WorkMode", WORK_MODE_VALUES["Collect"])
    time.sleep(0.2)

    try:
        drill.set_use_conveyor(True)
        time.sleep(0.1)
    except Exception as exc:
        print("WARNING: set_use_conveyor(True) failed:", exc)

    safe_action(drill, "CollectIfIdle_Off")
    safe_action(drill, "TerrainClearingMode_Off")


def configure_opening_mode(drill: NanobotDrillSystemDevice) -> None:
    print("Configuring rock opening mode...")

    safe_set(drill, "OnOff", False)
    time.sleep(0.2)
    safe_set(drill, "Drill.ShowArea", False)
    time.sleep(0.2)

    safe_action(drill, "CollectIfIdle_Off")
    safe_action(drill, "TerrainClearingMode_Off")

    for prop_name in (
        "Drill.CollectIfIdle",
        "Drill.TerrainClearingMode",
        "DrillSystem.CollectIfIdle",
        "DrillSystem.TerrainClearingMode",
    ):
        safe_set(drill, prop_name, False)
        time.sleep(0.05)

    try:
        drill.set_use_conveyor(False)
        time.sleep(0.2)
    except Exception as exc:
        print("WARNING: set_use_conveyor(False) failed:", exc)

    safe_set(drill, "Drill.ScriptControlled", True)
    time.sleep(0.2)

    # Не подбирать floating objects / лишние классы.
    try:
        drill.clear_collect_filter()
        time.sleep(0.2)
    except Exception as exc:
        print("WARNING: clear_collect_filter failed:", exc)

    # Для вскрытия разрешаем Stone и Platinum в DrillPriority:
    # Stone нужен для снятия крышки, Platinum нужен как индикатор появления в targets.
    # Как только Platinum появляется — скрипт сразу выключает бур.
    drill.set_ore_filters(["Stone", "Platinum"], work_mode="Drill")
    time.sleep(0.2)

    safe_set(drill, "Drill.WorkMode", WORK_MODE_VALUES["Drill"])
    time.sleep(0.2)

    safe_set(drill, "Drill.ScriptControlled", False)
    time.sleep(0.2)

    try:
        drill.set_script_controlled_action(False)
        time.sleep(0.2)
    except Exception as exc:
        print("WARNING: ScriptControlled_Off action failed:", exc)

    safe_set(drill, "Drill.WorkMode", WORK_MODE_VALUES["Drill"])
    time.sleep(0.2)


def set_area_to_target(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice,
    target: Tuple[float, float, float],
    area_width: float,
    area_height: float,
    area_depth: float,
) -> None:
    rc.update()
    time.sleep(0.3)
    rc.update()

    tel = rc.telemetry or {}
    rc_pos_raw = tel.get("position", {})
    orient = tel.get("orientation", {})
    if not rc_pos_raw or not orient:
        raise RuntimeError("No Remote Control telemetry with position/orientation")

    rc_pos = vector_from_dict(rc_pos_raw)
    fwd = vector_from_dict(orient["forward"])
    up = vector_from_dict(orient["up"])

    left_data = orient.get("left") or {}
    right_data = orient.get("right") or {}
    if left_data:
        left = vector_from_dict(left_data)
    elif right_data:
        right = vector_from_dict(right_data)
        left = v_mul(right, -1.0)
    else:
        left = v_mul(v_cross(fwd, up), -1.0)

    drill_local = get_drill_local_offset(grid, drill, rc)
    if drill_local is None:
        drill_local = (-2.5, 2.5, 5.0)
        print(f"Drill local offset fallback: {drill_local}")
    else:
        print(f"Drill local offset from metadata: {drill_local}")

    drill_world = v_add(
        rc_pos,
        v_add(
            v_mul(left, drill_local[0]),
            v_add(v_mul(up, drill_local[1]), v_mul(fwd, drill_local[2])),
        ),
    )

    delta = v_sub(target, drill_world)
    local_left = v_dot(delta, left)
    local_up = v_dot(delta, up)
    local_fwd = v_dot(delta, fwd)

    drill_fb, drill_ud, drill_lr = drill_offsets_from_grid_vector(local_left, local_up, local_fwd)
    mapped_left, mapped_up, mapped_fwd = grid_vector_from_drill_offsets(drill_fb, drill_ud, drill_lr)

    estimated_center = v_add(
        drill_world,
        v_add(v_mul(left, mapped_left), v_add(v_mul(up, mapped_up), v_mul(fwd, mapped_fwd))),
    )
    center_error = v_len(v_sub(target, estimated_center))

    print(f"Local vector to target: LR={local_left:.1f}, UD={local_up:.1f}, FB={local_fwd:.1f}")
    print(
        "Area offset to set using DRILL_AXIS_MAP: "
        f"FB={drill_fb:.1f} UD={drill_ud:.1f} LR={drill_lr:.1f}"
    )
    print(f"Drill to target: {v_len(delta):.1f}m")
    print(f"Estimated area center error: {center_error:.2f}m")

    safe_set(drill, "Drill.AreaOffsetFrontBack", round(drill_fb, 1))
    time.sleep(0.1)
    safe_set(drill, "Drill.AreaOffsetUpDown", round(drill_ud, 1))
    time.sleep(0.1)
    safe_set(drill, "Drill.AreaOffsetLeftRight", round(drill_lr, 1))
    time.sleep(0.1)

    safe_set(drill, "Drill.AreaWidth", float(area_width))
    time.sleep(0.1)
    safe_set(drill, "Drill.AreaHeight", float(area_height))
    time.sleep(0.1)
    safe_set(drill, "Drill.AreaDepth", float(area_depth))
    time.sleep(0.5)

    drill.update()
    actual_props = (drill.telemetry or {}).get("properties", {})
    print("Actual area properties after set:")
    for prop_name in (
        "Drill.AreaOffsetFrontBack",
        "Drill.AreaOffsetUpDown",
        "Drill.AreaOffsetLeftRight",
        "Drill.AreaWidth",
        "Drill.AreaHeight",
        "Drill.AreaDepth",
    ):
        print(f"  {prop_name}: {actual_props.get(prop_name)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear rock until Platinum becomes visible to Nanobot Drill")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--target", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"), help="World target coords")
    parser.add_argument("--ore", default="Platinum", help="Ore to wait for, default: Platinum")
    parser.add_argument("--area-size", type=float, default=3.0, help="Cube area size in meters, default: 3")
    parser.add_argument("--area-width", type=float, default=None, help="Area width override")
    parser.add_argument("--area-height", type=float, default=None, help="Area height override")
    parser.add_argument("--area-depth", type=float, default=None, help="Area depth override")
    parser.add_argument("--check-interval", type=float, default=1.0, help="Target polling interval in seconds")
    parser.add_argument("--max-seconds", type=float, default=180.0, help="Maximum clearing time")
    parser.add_argument("--target-dump", type=int, default=20, help="How many targets to print on stop/diagnostics")
    parser.add_argument("--max-stone-delta", type=float, default=-1.0,
                        help="Stop if grid Stone delta exceeds this value; negative disables this safety")
    parser.add_argument("--leave-area-visible", action="store_true", help="Keep ShowArea enabled after stopping")
    parser.add_argument("--no-ready-platinum", action="store_true",
                        help="Do not reconfigure to safe Platinum collect mode after Platinum appears")
    args = parser.parse_args()

    if args.ore.lower() not in ORE_HASHES:
        print(f"ERROR: unknown ore '{args.ore}'. Known ores: {', '.join(sorted(ORE_HASHES))}")
        return 1

    area_width = args.area_width if args.area_width is not None else args.area_size
    area_height = args.area_height if args.area_height is not None else args.area_size
    area_depth = args.area_depth if args.area_depth is not None else args.area_size

    grid = Grid.from_name(args.grid)
    print(f"Grid: {grid.name} (id={grid.grid_id})")

    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("ERROR: No Nanobot Drill found")
        return 1
    drill = drills[0]
    print(f"Drill: {drill.name} (id={drill.device_id})")

    rc_devices = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_devices:
        print("ERROR: No Remote Control found")
        return 1
    rc = rc_devices[0]
    print(f"RC: {rc.name} (id={rc.device_id})")

    target = tuple(args.target)
    baseline_ore = get_ore_amount(grid, args.ore)
    baseline_stone = get_item_amount(grid, "Stone")

    print(f"Baseline {args.ore}: {baseline_ore:.1f}")
    print(f"Baseline Stone: {baseline_stone:.1f}")
    print(f"Target: {target}")
    print(f"Opening area: width={area_width} height={area_height} depth={area_depth}")
    print()

    configure_opening_mode(drill)
    print_raw_filters(drill)
    print()

    # WorkMode сбрасывает AreaOffset, поэтому AreaOffset ставится только после configure_opening_mode().
    set_area_to_target(grid, drill, rc, target, area_width, area_height, area_depth)

    current, targets, props = read_targets(drill)
    ore_targets = [t for t in targets if target_has_ore(t, args.ore)]
    print(f"Preflight before opening: Targets={len(targets)}, {args.ore}={len(ore_targets)}, Current={current}")
    if ore_targets:
        print(f"{args.ore} is already visible. Drill will not start.")
        dump_targets(targets, args.ore, args.target_dump)
        stop_drill(drill, keep_area=args.leave_area_visible)
        if not args.no_ready_platinum and args.ore.lower() == "platinum":
            configure_platinum_collect_ready(drill)
            set_area_to_target(grid, drill, rc, target, area_width, area_height, area_depth)
        return 0

    print("Starting rock opening...")
    safe_set(drill, "Drill.ShowArea", True)
    time.sleep(0.2)
    safe_set(drill, "OnOff", True)

    start = time.time()
    last_print = 0.0
    found = False

    while True:
        time.sleep(max(0.2, args.check_interval))
        elapsed = time.time() - start

        current, targets, props = read_targets(drill)
        ore_targets = [t for t in targets if target_has_ore(t, args.ore)]
        current_ok = current is not None and current_has_ore(current, targets, args.ore)

        ore_delta = get_ore_amount(grid, args.ore) - baseline_ore
        stone_delta = get_item_amount(grid, "Stone") - baseline_stone

        if ore_targets or current_ok or ore_delta > 0.01:
            found = True
            print()
            print(f"FOUND {args.ore} after {elapsed:.1f}s. Stopping drill immediately.")
            print(f"Targets={len(targets)}, {args.ore}={len(ore_targets)}, Current={current}")
            print(f"{args.ore} delta: +{ore_delta:.1f}; Stone delta: +{stone_delta:.1f}")
            dump_targets(targets, args.ore, args.target_dump)
            break

        if args.max_stone_delta >= 0.0 and stone_delta > args.max_stone_delta:
            print()
            print("SAFETY STOP: Stone delta exceeded limit during opening.")
            print(f"Limit: +{args.max_stone_delta:.1f}; Stone delta: +{stone_delta:.1f}; {args.ore} delta: +{ore_delta:.1f}")
            print(f"Targets={len(targets)}, {args.ore}={len(ore_targets)}, Current={current}")
            dump_targets(targets, args.ore, args.target_dump)
            break

        if elapsed >= args.max_seconds:
            print()
            print("TIMEOUT: requested ore did not appear during opening.")
            print(f"Elapsed: {elapsed:.1f}s; max: {args.max_seconds:.1f}s")
            print(f"Targets={len(targets)}, {args.ore}={len(ore_targets)}, Current={current}")
            print(f"{args.ore} delta: +{ore_delta:.1f}; Stone delta: +{stone_delta:.1f}")
            dump_targets(targets, args.ore, args.target_dump)
            break

        if elapsed - last_print >= 5.0 or last_print == 0.0:
            last_print = elapsed
            print(
                f"  [{elapsed:.0f}/{args.max_seconds:.0f}s] "
                f"targets={len(targets)}, {args.ore}={len(ore_targets)}, "
                f"{args.ore} +{ore_delta:.1f}, Stone +{stone_delta:.1f}, current={current}"
            )

    stop_drill(drill, keep_area=args.leave_area_visible)

    if found and not args.no_ready_platinum and args.ore.lower() == "platinum":
        # Переводим бур в безопасный режим добычи платины и снова ставим AreaOffset,
        # потому что WorkMode сбрасывает офсеты.
        configure_platinum_collect_ready(drill)
        set_area_to_target(grid, drill, rc, target, area_width, area_height, area_depth)
        print()
        print("Ready: Platinum collect filter is configured, area is restored, drill is OFF.")
        print("Next command can be mine_until.py with normal stone safety.")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
