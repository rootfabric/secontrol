#!/usr/bin/env python3
"""
sweep_clear_until_ore_visible.py — аккуратно вскрывает камень маленькой зоной
и останавливается, как только выбранная руда появляется в PossibleDrillTargets.

Идея:
  1. Бур работает в режиме Drill маленькой областью.
  2. Камень разрешён только для вскрытия, сбор предметов отключён.
  3. Скрипт двигает центр области вокруг исходной точки по 3D-сетке.
  4. Как только в targets/current появляется нужная руда — бур сразу выключается.
  5. По умолчанию после нахождения руда-фильтр ставится в безопасный Collect-only режим.

Пример:
  python examples/organized/drill_nano/sweep_clear_until_ore_visible.py ^
    --grid skynet-baza1 ^
    --ore Platinum ^
    --target -56801.387 146493.057 -134209.677 ^
    --area-size 5 ^
    --radius 25 ^
    --step 5 ^
    --clear-seconds-per-point 12 ^
    --max-total-seconds 600 ^
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
RESOURCE_CLASS_NAMES = {2: "Ingot", 3: "Ore", 4: "Stone", 5: "Gravel"}

# Должно совпадать с рабочим set_nanodrill_area.py для skynet-baza.
# Grid vector order: [Left/X, Up/Y, Forward/Z]
# Drill properties:  [LeftRight, UpDown, FrontBack]
DRILL_AXIS_MAP = {
    "LeftRight": (0, 1),
    "UpDown": (2, 1),
    "FrontBack": (1, 1),
}


Vector = Tuple[float, float, float]


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(value or "").lower())


def vector_from_dict(data: Dict[str, Any]) -> Vector:
    return float(data["x"]), float(data["y"]), float(data["z"])


def v_add(a: Vector, b: Vector) -> Vector:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def v_sub(a: Vector, b: Vector) -> Vector:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def v_mul(a: Vector, k: float) -> Vector:
    return a[0] * k, a[1] * k, a[2] * k


def v_dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_len(a: Vector) -> float:
    return math.sqrt(v_dot(a, a))


def v_cross(a: Vector, b: Vector) -> Vector:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def format_point(point: Vector) -> str:
    return f"{point[0]:.3f} {point[1]:.3f} {point[2]:.3f}"


def get_item_amount(grid: Grid, item_subtype: str) -> float:
    total = 0.0
    wanted = item_subtype.lower()

    for item in grid.get_all_grid_items():
        subtype = str(item.get("item_subtype", ""))
        display = str(item.get("display_name", ""))
        if subtype.lower() == wanted or display.lower() == wanted:
            total += float(item.get("amount", 0) or 0)

    return total


def _inventory_text(item: Dict[str, Any], *keys: str) -> str:
    return " ".join(str(item.get(key, "")) for key in keys if item.get(key) is not None).lower()


def _looks_like_refined_or_component(item: Dict[str, Any]) -> bool:
    text = _inventory_text(
        item,
        "item_type",
        "item_type_id",
        "type_id",
        "type",
        "content_type",
        "definition_type",
        "display_name",
    )
    return any(token in text for token in ("ingot", "component", "ammo", "tool", "physicalgunobject"))


def _looks_like_ore_item(item: Dict[str, Any], wanted: str) -> bool:
    subtype = str(item.get("item_subtype", "")).strip().lower()
    display = str(item.get("display_name", "")).strip().lower()
    type_text = _inventory_text(
        item,
        "item_type",
        "item_type_id",
        "type_id",
        "type",
        "content_type",
        "definition_type",
    )

    if _looks_like_refined_or_component(item):
        return False
    if "myobjectbuilder_ore" in type_text or type_text.strip() == "ore" or type_text.endswith(" ore"):
        return subtype == wanted or display == wanted or f"{wanted} ore" in display or wanted in subtype
    if subtype == wanted and (" ore" in display or display == wanted or wanted == "ice"):
        return True
    if f"{wanted} ore" in display:
        return True
    return False


def get_ore_amount(grid: Grid, ore_subtype: str) -> float:
    """Return only raw ore amount, never ingots/components."""
    wanted = ore_subtype.strip().lower()
    total = 0.0

    for item in grid.get_all_grid_items():
        if isinstance(item, dict) and _looks_like_ore_item(item, wanted):
            total += float(item.get("amount", 0) or 0)

    return total


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
        elif isinstance(target, dict):
            text = target.get("target") or target.get("text") or target.get("current")
            if text is not None and str(text) == current_text:
                return target_has_ore(target, ore_subtype)

    return target_has_ore(current, ore_subtype)


def read_targets(drill: NanobotDrillSystemDevice) -> Tuple[Any, List[Any], Dict[str, Any]]:
    drill.update()
    tel = drill.telemetry or {}
    props = tel.get("properties", {})
    current = props.get("Drill.CurrentDrillTarget")
    targets = tel.get("drill_possibledrilltargets", []) or []
    return current, targets, props


def dump_targets(targets: List[Any], ore_subtype: str, limit: int) -> None:
    print(f"Possible targets dump, first {min(limit, len(targets))}/{len(targets)}:")
    for index, target in enumerate(targets[:limit]):
        distance = target_distance(target)
        amount = target_amount(target)
        material = target_material_text(target)
        mark = "<-- requested" if target_has_ore(target, ore_subtype) else ""
        distance_text = f"dist={distance:.1f}" if distance is not None else "dist=?"
        amount_text = f"amount={amount:.1f}" if amount is not None else "amount=?"
        print(f"  #{index:02d}: {distance_text}, {amount_text}, material={material} {mark}")


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


def get_block_local_position(grid: Grid, device_id: int | str) -> Optional[Vector]:
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
) -> Optional[Vector]:
    drill_pos = get_block_local_position(grid, drill.device_id)
    rc_pos = get_block_local_position(grid, rc.device_id)

    if drill_pos is None or rc_pos is None:
        return None

    return (
        drill_pos[0] - rc_pos[0],
        drill_pos[1] - rc_pos[1],
        drill_pos[2] - rc_pos[2],
    )


def get_navigation_frame(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice,
) -> Tuple[Vector, Vector, Vector, Vector, Vector]:
    rc.update()
    time.sleep(0.3)
    rc.update()

    tel = rc.telemetry or {}
    rc_pos_raw = tel.get("position", {})
    orient = tel.get("orientation", {})

    if not rc_pos_raw or not orient:
        raise RuntimeError("No RC position/orientation telemetry")

    rc_pos = vector_from_dict(rc_pos_raw)
    fwd = vector_from_dict(orient["forward"])
    up = vector_from_dict(orient["up"])

    left_data = orient.get("left") or {}
    right_data = orient.get("right") or {}
    if left_data:
        left = vector_from_dict(left_data)
    elif right_data:
        left = v_mul(vector_from_dict(right_data), -1.0)
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
        v_add(v_mul(left, drill_local[0]), v_add(v_mul(up, drill_local[1]), v_mul(fwd, drill_local[2]))),
    )

    return drill_world, left, up, fwd, drill_local


def drill_offsets_from_local_vector(local_left: float, local_up: float, local_fwd: float) -> Tuple[float, float, float]:
    grid_vec = [local_left, local_up, local_fwd]

    def remap(prop_name: str) -> float:
        axis, sign = DRILL_AXIS_MAP[prop_name]
        return grid_vec[axis] * sign

    frontback = remap("FrontBack")
    updown = remap("UpDown")
    leftright = remap("LeftRight")
    return frontback, updown, leftright


def set_area_to_world_target(
    drill: NanobotDrillSystemDevice,
    drill_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    target_world: Vector,
    area_size: float,
    delay: float = 0.08,
) -> Tuple[float, float, float, float]:
    delta = v_sub(target_world, drill_world)

    local_left = v_dot(delta, left)
    local_up = v_dot(delta, up)
    local_fwd = v_dot(delta, fwd)

    drill_fb, drill_ud, drill_lr = drill_offsets_from_local_vector(local_left, local_up, local_fwd)

    drill.set_raw_property("Drill.AreaOffsetFrontBack", round(drill_fb, 2))
    time.sleep(delay)
    drill.set_raw_property("Drill.AreaOffsetUpDown", round(drill_ud, 2))
    time.sleep(delay)
    drill.set_raw_property("Drill.AreaOffsetLeftRight", round(drill_lr, 2))
    time.sleep(delay)

    drill.set_raw_property("Drill.AreaWidth", float(area_size))
    time.sleep(delay)
    drill.set_raw_property("Drill.AreaHeight", float(area_size))
    time.sleep(delay)
    drill.set_raw_property("Drill.AreaDepth", float(area_size))
    time.sleep(delay)

    return drill_fb, drill_ud, drill_lr, v_len(delta)


def world_from_base_and_local_offset(
    base_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    offset: Vector,
) -> Vector:
    local_left, local_up, local_fwd = offset
    return v_add(base_world, v_add(v_mul(left, local_left), v_add(v_mul(up, local_up), v_mul(fwd, local_fwd))))


def generate_local_offsets(radius: float, step: float, max_points: int) -> List[Vector]:
    if radius < 0:
        raise ValueError("radius must be >= 0")
    if step <= 0:
        raise ValueError("step must be > 0")

    offsets: List[Vector] = []
    count = int(math.floor(radius / step))

    for ix in range(-count, count + 1):
        for iy in range(-count, count + 1):
            for iz in range(-count, count + 1):
                offset = (ix * step, iy * step, iz * step)
                if v_len(offset) <= radius + 1e-6:
                    offsets.append(offset)

    offsets.sort(key=lambda p: (v_len(p), abs(p[2]), abs(p[1]), abs(p[0]), p[2], p[1], p[0]))

    if max_points > 0:
        offsets = offsets[:max_points]

    return offsets


def safe_action(drill: NanobotDrillSystemDevice, action_id: str) -> None:
    try:
        drill.run_action(action_id)
    except Exception as exc:
        print(f"WARNING: action {action_id} failed: {exc}")


def safe_set_raw(drill: NanobotDrillSystemDevice, property_name: str, value: Any) -> None:
    try:
        drill.set_raw_property(property_name, value)
    except Exception:
        pass


def configure_opening_mode(drill: NanobotDrillSystemDevice, ore_subtype: str) -> None:
    drill.set_raw_property("OnOff", False)
    time.sleep(0.2)
    drill.set_raw_property("Drill.ShowArea", False)
    time.sleep(0.2)

    safe_action(drill, "CollectIfIdle_Off")
    safe_action(drill, "TerrainClearingMode_Off")

    for prop_name in (
        "Drill.CollectIfIdle",
        "Drill.TerrainClearingMode",
        "DrillSystem.CollectIfIdle",
        "DrillSystem.TerrainClearingMode",
        "UseConveyor",
        "Drill.UseConveyor",
        "DrillSystem.UseConveyor",
    ):
        safe_set_raw(drill, prop_name, False)
        time.sleep(0.05)

    drill.set_raw_property("Drill.ScriptControlled", True)
    time.sleep(0.2)

    try:
        drill.clear_collect_filter()
        time.sleep(0.2)
    except Exception as exc:
        print("WARNING: clear_collect_filter failed:", exc)

    # Для вскрытия разрешаем только камень и целевую руду.
    # Если попадём в целевую руду, скрипт остановится почти сразу.
    drill.set_ore_filters(["Stone", ore_subtype], work_mode="Drill")
    time.sleep(0.2)

    drill.set_raw_property("Drill.WorkMode", WORK_MODE_VALUES["Drill"])
    time.sleep(0.2)
    drill.set_raw_property("Drill.ScriptControlled", False)
    time.sleep(0.2)
    drill.set_raw_property("Drill.WorkMode", WORK_MODE_VALUES["Drill"])
    time.sleep(0.2)

    # Повторно выключаем сбор после смены режима.
    safe_action(drill, "CollectIfIdle_Off")
    safe_set_raw(drill, "Drill.CollectIfIdle", False)
    safe_set_raw(drill, "DrillSystem.CollectIfIdle", False)
    safe_set_raw(drill, "UseConveyor", False)
    safe_set_raw(drill, "Drill.UseConveyor", False)
    safe_set_raw(drill, "DrillSystem.UseConveyor", False)
    time.sleep(0.2)


def configure_safe_collect_mode(
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    drill_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    target_world: Vector,
    area_size: float,
) -> None:
    drill.set_raw_property("OnOff", False)
    time.sleep(0.2)
    drill.set_raw_property("Drill.ShowArea", False)
    time.sleep(0.2)

    drill.set_raw_property("Drill.ScriptControlled", True)
    time.sleep(0.2)
    drill.set_collect_filter(["Ore"])
    time.sleep(0.2)
    drill.set_ore_filters([ore_subtype], work_mode="Collect")
    time.sleep(0.2)
    drill.set_raw_property("Drill.WorkMode", WORK_MODE_VALUES["Collect"])
    time.sleep(0.2)
    drill.set_raw_property("Drill.ScriptControlled", False)
    time.sleep(0.2)
    drill.set_raw_property("Drill.WorkMode", WORK_MODE_VALUES["Collect"])
    time.sleep(0.2)

    safe_action(drill, "CollectIfIdle_Off")
    safe_action(drill, "TerrainClearingMode_Off")
    safe_set_raw(drill, "Drill.CollectIfIdle", False)
    safe_set_raw(drill, "Drill.TerrainClearingMode", False)
    safe_set_raw(drill, "DrillSystem.CollectIfIdle", False)
    safe_set_raw(drill, "DrillSystem.TerrainClearingMode", False)

    set_area_to_world_target(drill, drill_world, left, up, fwd, target_world, area_size)
    drill.set_raw_property("Drill.ShowArea", True)
    time.sleep(0.2)
    drill.set_raw_property("OnOff", False)



# NANODRILL_DYNAMIC_AREA_FIX
# AreaOffset is Nanobot-block-local. These overrides replace the old fixed
# DRILL_AXIS_MAP logic and use Nanobot position/orientation telemetry.
try:
    from nanodrill_area_frame import (
        get_navigation_frame as _dynamic_get_navigation_frame,
        set_area_to_world_target as _dynamic_set_area_to_world_target,
        drill_offsets_from_local_vector as _dynamic_drill_offsets_from_local_vector,
        world_from_base_and_local_offset as _dynamic_world_from_base_and_local_offset,
    )

    def get_navigation_frame(grid, drill, rc):
        drill_world, left, up, fwd = _dynamic_get_navigation_frame(grid, drill, rc)
        return drill_world, left, up, fwd, (0.0, 0.0, 0.0)

    set_area_to_world_target = _dynamic_set_area_to_world_target
    drill_offsets_from_local_vector = _dynamic_drill_offsets_from_local_vector
    world_from_base_and_local_offset = _dynamic_world_from_base_and_local_offset
except Exception as _dynamic_area_import_error:
    print(f"WARNING: dynamic Nanobot area helper unavailable: {_dynamic_area_import_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear stone in a small sweep until ore appears in Nanobot Drill targets")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--ore", default="Platinum", help="Ore type to reveal, e.g. Platinum")
    parser.add_argument("--target", nargs=3, type=float, metavar=("X", "Y", "Z"), required=True, help="Base world coords")
    parser.add_argument("--area-size", type=float, default=5.0, help="Area width/height/depth in meters")
    parser.add_argument("--radius", type=float, default=25.0, help="Sweep radius around target in grid-local meters")
    parser.add_argument("--step", type=float, default=5.0, help="Sweep step in meters")
    parser.add_argument("--max-points", type=int, default=300, help="Maximum sweep points; 0 means no limit")
    parser.add_argument("--clear-seconds-per-point", type=float, default=12.0, help="How long to clear each point")
    parser.add_argument("--check-interval", type=float, default=1.0, help="How often to check targets")
    parser.add_argument("--max-total-seconds", type=float, default=600.0, help="Total safety timeout")
    parser.add_argument("--max-stone-delta", type=float, default=100000.0, help="Stop if Stone delta exceeds this value; 0 disables")
    parser.add_argument("--target-dump", type=int, default=20, help="How many targets to print on finish/found")
    parser.add_argument("--no-ready-collect", action="store_true", help="Do not configure safe Collect mode after ore is found")
    args = parser.parse_args()

    wanted = args.ore.strip()
    if not wanted:
        print("ERROR: ore must not be empty")
        return 1
    if wanted.lower() not in ORE_HASHES:
        print(f"ERROR: unknown ore '{wanted}'. Known ores: {', '.join(sorted(ORE_HASHES))}")
        return 1

    if args.area_size <= 0:
        print("ERROR: --area-size must be > 0")
        return 1
    if args.step <= 0:
        print("ERROR: --step must be > 0")
        return 1

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

    base_target = (float(args.target[0]), float(args.target[1]), float(args.target[2]))
    baseline_ore = get_ore_amount(grid, wanted)
    baseline_stone = get_item_amount(grid, "Stone")

    print(f"Base target: {format_point(base_target)}")
    print(f"Opening area size: {args.area_size:.1f}m")
    print(f"Sweep radius: {args.radius:.1f}m, step: {args.step:.1f}m")
    print(f"Baseline {wanted}: {baseline_ore:.1f}")
    print(f"Baseline Stone: {baseline_stone:.1f}")
    print()

    print("Configuring opening mode...")
    configure_opening_mode(drill, wanted)
    print_raw_filters(drill)
    print()

    drill_world, left, up, fwd, _drill_local = get_navigation_frame(grid, drill, rc)
    offsets = generate_local_offsets(args.radius, args.step, args.max_points)
    if not offsets:
        print("ERROR: no sweep points generated")
        return 1

    print(f"Generated sweep points: {len(offsets)}")
    print("Starting sweep clearing...")
    print()

    start_time = time.time()
    found = False
    found_world = base_target
    found_offset = (0.0, 0.0, 0.0)
    last_targets: List[Any] = []
    last_current: Any = None

    try:
        for point_index, local_offset in enumerate(offsets, start=1):
            elapsed_total = time.time() - start_time
            if elapsed_total >= args.max_total_seconds:
                print(f"SAFETY STOP: max total timeout {args.max_total_seconds:.1f}s reached")
                break

            target_world = world_from_base_and_local_offset(base_target, left, up, fwd, local_offset)
            found_world = target_world
            found_offset = local_offset

            drill.set_raw_property("OnOff", False)
            time.sleep(0.15)

            drill_fb, drill_ud, drill_lr, distance_to_drill = set_area_to_world_target(
                drill,
                drill_world,
                left,
                up,
                fwd,
                target_world,
                args.area_size,
            )

            drill.set_raw_property("Drill.ShowArea", True)
            time.sleep(0.1)
            drill.set_raw_property("OnOff", True)

            print(
                f"[point {point_index}/{len(offsets)}] "
                f"local offset LR={local_offset[0]:+.1f} UP={local_offset[1]:+.1f} FW={local_offset[2]:+.1f}; "
                f"world={format_point(target_world)}; "
                f"area FB={drill_fb:+.1f} UD={drill_ud:+.1f} LR={drill_lr:+.1f}; "
                f"dist={distance_to_drill:.1f}m"
            )

            point_start = time.time()
            last_print = 0.0

            while time.time() - point_start < args.clear_seconds_per_point:
                time.sleep(max(0.2, args.check_interval))

                current, targets, _props = read_targets(drill)
                last_targets = targets
                last_current = current

                ore_targets = [target for target in targets if target_has_ore(target, wanted)]
                current_ok = current is not None and current_has_ore(current, targets, wanted)
                ore_delta = get_ore_amount(grid, wanted) - baseline_ore
                stone_delta = get_item_amount(grid, "Stone") - baseline_stone

                if ore_targets or current_ok or ore_delta > 0.01:
                    found = True
                    elapsed_total = time.time() - start_time
                    print()
                    print(f"FOUND {wanted} after {elapsed_total:.1f}s at sweep point {point_index}/{len(offsets)}")
                    print(f"Found world target: {format_point(target_world)}")
                    print(
                        f"Found local offset from base: "
                        f"LR={local_offset[0]:+.1f} UP={local_offset[1]:+.1f} FW={local_offset[2]:+.1f}"
                    )
                    print(
                        f"targets={len(targets)}, {wanted}={len(ore_targets)}, "
                        f"{wanted} +{ore_delta:.1f}, Stone +{stone_delta:.1f}, current={current}"
                    )
                    if targets:
                        dump_targets(targets, wanted, args.target_dump)
                    break

                if args.max_stone_delta > 0 and stone_delta > args.max_stone_delta:
                    print()
                    print("SAFETY STOP: Stone delta limit reached during sweep")
                    print(f"Stone delta: +{stone_delta:.1f}; limit: +{args.max_stone_delta:.1f}")
                    print(f"Current: {current}")
                    print(f"Targets={len(targets)}, {wanted}=0")
                    if targets:
                        dump_targets(targets, wanted, args.target_dump)
                    drill.set_raw_property("OnOff", False)
                    drill.set_raw_property("Drill.ShowArea", False)
                    return 2

                elapsed_point = time.time() - point_start
                if elapsed_point - last_print >= 5.0 or last_print == 0.0:
                    last_print = elapsed_point
                    print(
                        f"  [{elapsed_point:.0f}/{args.clear_seconds_per_point:.0f}s] "
                        f"targets={len(targets)}, {wanted}=0, "
                        f"{wanted} +{ore_delta:.1f}, Stone +{stone_delta:.1f}, current={current}"
                    )

            if found:
                break

    finally:
        drill.set_raw_property("OnOff", False)
        time.sleep(0.2)

    if not found:
        elapsed_total = time.time() - start_time
        print()
        print(f"NOT FOUND: {wanted} did not appear after {elapsed_total:.1f}s")
        print(f"Last current: {last_current}")
        print(f"Last targets: {len(last_targets)}")
        if last_targets:
            dump_targets(last_targets, wanted, args.target_dump)
        print("Drill is OFF.")
        drill.set_raw_property("Drill.ShowArea", False)
        return 5

    print("Stopping drill immediately...")
    drill.set_raw_property("OnOff", False)
    time.sleep(0.2)

    if args.no_ready_collect:
        print("Ready collect mode skipped by --no-ready-collect.")
        print(f"Use this target for mining: {format_point(found_world)}")
        return 0

    print(f"Configuring safe {wanted}-only Collect mode at found point...")
    configure_safe_collect_mode(drill, wanted, drill_world, left, up, fwd, found_world, args.area_size)

    print_raw_filters(drill)
    print()
    print(f"READY: {wanted}-only Collect filter is configured. Drill is OFF.")
    print(f"Found target world coords: {format_point(found_world)}")
    print()
    print("Next command:")
    print(
        f"python examples/organized/drill_nano/mine_until.py "
        f"--grid {args.grid} "
        f"--ore {wanted} "
        f"--target {format_point(found_world)} "
        f"--amount 5000 "
        f"--check-interval 30 "
        f"--start-check-timeout 60 "
        f"--start-check-interval 2 "
        f"--startup-stone-grace 0 "
        f"--max-start-stone-delta 1 "
        f"--target-dump {args.target_dump}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
