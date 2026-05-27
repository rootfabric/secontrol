#!/usr/bin/env python3
"""Sticky robot-grade Nanobot ore miner for Space Engineers.

The script performs a full mining cycle in one command:
  1. Stop the Nanobot and wait until old work settles.
  2. Scan ore cells with OreDetectorDevice.scan_and_wait(ore_only=True).
  3. Pick dense internal points of the requested ore cluster.
  4. Configure Nanobot in strict Collect mode: CollectFilter=Ore, OreFilter=<ore>.
  5. Aim the Nanobot area at candidate scan points.
  6. Preflight targets and mine when either targets/current show the requested ore
     or inventory delta proves that the requested ore is being collected.
  7. Stop immediately on wrong WorkMode or unsafe Stone growth.

Recommended default for Platinum:
  python examples/organized/drill_nano/mine_ore_robot_live_move.py --grid skynet-baza1 --ore Platinum --amount 5000

Live move mode:
  With --live-move the Nanobot may stay powered while the area is shifted between
  empty points. If the Nanobot reports a wrong Stone target, the script now stops
  before moving to the next point. Keeping power on while a wrong target is active
  can pollute cargo with Stone.
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
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


WORK_MODE_VALUES: Dict[str, int] = {
    "Drill": 1,
    "Collect": 2,
    "Fill": 4,
}

COLLECT_MODE = WORK_MODE_VALUES["Collect"]

ORE_HASH_BY_NAME: Dict[str, int] = {
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

ORE_NAME_BY_HASH: Dict[int, str] = {value: key for key, value in ORE_HASH_BY_NAME.items()}

RESOURCE_CLASSES: Dict[int, str] = {
    1: "unknown",
    2: "ingot",
    3: "ore",
    4: "stone",
    5: "gravel",
}

# Grid vector order: [Left/X, Up/Y, Forward/Z]
# Nanobot terminal properties: [LeftRight, UpDown, FrontBack]
# This map matches the current skynet-baza Nanobot mount used by the existing scripts.
DRILL_AXIS_MAP: Dict[str, Tuple[int, int]] = {
    "LeftRight": (0, 1),
    "UpDown": (2, 1),
    "FrontBack": (1, 1),
}

Vector = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(value or "").lower())


def canonical_ore_name(value: str) -> str:
    key = normalize_text(value)
    for name in ORE_HASH_BY_NAME:
        if normalize_text(name) == key:
            return name.capitalize()
    raise ValueError(f"Unknown ore '{value}'. Known ores: {', '.join(sorted(ORE_HASH_BY_NAME))}")


def format_point(point: Vector) -> str:
    return f"{point[0]:.3f} {point[1]:.3f} {point[2]:.3f}"


def vector_from_dict(data: Dict[str, Any]) -> Vector:
    return float(data["x"]), float(data["y"]), float(data["z"])


def point_from_any(value: Any) -> Optional[Vector]:
    if isinstance(value, dict) and {"x", "y", "z"}.issubset(value.keys()):
        try:
            return float(value["x"]), float(value["y"]), float(value["z"])
        except (TypeError, ValueError):
            return None

    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return float(value[0]), float(value[1]), float(value[2])
        except (TypeError, ValueError):
            return None

    return None


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


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------


def get_item_amount(grid: Grid, item_subtype: str) -> float:
    wanted = item_subtype.lower()
    total = 0.0

    for item in grid.get_all_grid_items():
        subtype = str(item.get("item_subtype", ""))
        display = str(item.get("display_name", ""))
        if subtype.lower() == wanted or display.lower() == wanted:
            total += float(item.get("amount", 0) or 0)

    return total


def get_ore_amount(grid: Grid, ore_subtype: str) -> float:
    wanted = ore_subtype.lower()
    total = 0.0

    for item in grid.get_all_grid_items():
        subtype = str(item.get("item_subtype", ""))
        display = str(item.get("display_name", ""))
        if wanted in subtype.lower() or wanted in display.lower():
            total += float(item.get("amount", 0) or 0)

    return total


# ---------------------------------------------------------------------------
# Target parsing helpers
# ---------------------------------------------------------------------------


def material_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, dict):
        keys = (
            "minedOre",
            "mined_ore",
            "MinedOre",
            "subtype",
            "SubtypeName",
            "subtypeName",
            "name",
            "Name",
            "type",
            "Type",
        )
        parts: List[str] = []
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


def read_targets(drill: NanobotDrillSystemDevice) -> Tuple[Any, List[Any], Dict[str, Any]]:
    drill.update()
    telemetry = drill.telemetry or {}
    props = telemetry.get("properties", {})
    current = props.get("Drill.CurrentDrillTarget") if isinstance(props, dict) else None
    targets = telemetry.get("drill_possibledrilltargets", []) or []
    return current, targets, props if isinstance(props, dict) else {}


def dump_targets(targets: List[Any], ore_subtype: str, limit: int) -> None:
    print(f"Targets dump, first {min(limit, len(targets))}/{len(targets)}:")
    for index, target in enumerate(targets[:limit]):
        distance = target_distance(target)
        amount = target_amount(target)
        material = target_material_text(target)
        mark = "<-- requested" if target_has_ore(target, ore_subtype) else ""
        distance_text = f"dist={distance:.1f}" if distance is not None else "dist=?"
        amount_text = f"amount={amount:.1f}" if amount is not None else "amount=?"
        print(f"  #{index:02d}: {distance_text}, {amount_text}, material={material} {mark}")


# ---------------------------------------------------------------------------
# Device and telemetry helpers
# ---------------------------------------------------------------------------


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


def run_action(drill: NanobotDrillSystemDevice, action_id: str) -> None:
    try:
        drill.run_action(action_id)
    except Exception as exc:
        print(f"WARNING: action {action_id} failed: {exc}")


def safe_set_raw(drill: NanobotDrillSystemDevice, property_name: str, value: Any) -> None:
    try:
        drill.set_raw_property(property_name, value)
    except Exception as exc:
        print(f"WARNING: set {property_name}={value!r} failed: {exc}")


def find_drill(grid: Grid, name_filter: Optional[str]) -> NanobotDrillSystemDevice:
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        raise RuntimeError("No Nanobot Drill found")

    if not name_filter:
        return drills[0]

    wanted = name_filter.lower()
    for drill in drills:
        if wanted in drill.name.lower():
            return drill

    names = ", ".join(drill.name for drill in drills)
    raise RuntimeError(f"No Nanobot Drill name contains '{name_filter}'. Available: {names}")


def find_remote_control(grid: Grid) -> RemoteControlDevice:
    devices = grid.find_devices_by_type(RemoteControlDevice)
    if not devices:
        raise RuntimeError("No Remote Control found")
    return devices[0]


def send_collect_filter(drill: NanobotDrillSystemDevice, resources: List[str]) -> int:
    return drill.send_command({"command": "CollectFilter", "payload": {"resources": resources}})


def send_ore_filter(drill: NanobotDrillSystemDevice, ores: List[str], work_mode: int) -> int:
    return drill.send_command(
        {
            "command": "OreFilter",
            "payload": {
                "ores": ores,
                "workMode": int(work_mode),
                "applyCollectFilter": True,
            },
        }
    )


def get_props(drill: NanobotDrillSystemDevice) -> Dict[str, Any]:
    drill.update()
    telemetry = drill.telemetry or {}
    props = telemetry.get("properties", {})
    return props if isinstance(props, dict) else {}


def get_work_mode_raw(drill: NanobotDrillSystemDevice) -> Optional[int]:
    value = get_props(drill).get("Drill.WorkMode")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def hard_stop(drill: NanobotDrillSystemDevice, hide_area: bool = True) -> None:
    run_action(drill, "OnOff_Off")
    safe_set_raw(drill, "OnOff", False)
    time.sleep(0.15)
    if hide_area:
        safe_set_raw(drill, "Drill.ShowArea", False)
        time.sleep(0.1)


def wait_idle(grid: Grid, drill: NanobotDrillSystemDevice, seconds: float, label: str) -> None:
    if seconds <= 0:
        return

    start = time.time()
    last_stone = get_item_amount(grid, "Stone")

    while time.time() - start < seconds:
        time.sleep(0.5)
        current, targets, _props = read_targets(drill)
        stone = get_item_amount(grid, "Stone")
        delta = stone - last_stone
        last_stone = stone
        print(
            f"  cooldown {label}: {time.time() - start:.1f}/{seconds:.1f}s, "
            f"targets={len(targets)}, current={current}, StoneStep={delta:+.1f}"
        )


def force_collect_mode(drill: NanobotDrillSystemDevice, delay: float = 0.25) -> None:
    safe_set_raw(drill, "Drill.WorkMode", COLLECT_MODE)
    time.sleep(delay)
    run_action(drill, "Collect_On")
    time.sleep(delay)


def raw_ore_state(drill: NanobotDrillSystemDevice) -> Dict[str, bool]:
    result: Dict[str, bool] = {}
    for entry in drill.debug_get_priority_list_raw():
        parsed = parse_priority_entry(entry)
        if parsed is None:
            continue
        ore_hash, enabled = parsed
        name = ORE_NAME_BY_HASH.get(ore_hash)
        if name:
            result[name] = enabled
    return result


def raw_resource_state(drill: NanobotDrillSystemDevice) -> Dict[str, bool]:
    result: Dict[str, bool] = {}
    for entry in drill.debug_get_collect_priority_list_raw():
        parsed = parse_priority_entry(entry)
        if parsed is None:
            continue
        key, enabled = parsed
        name = RESOURCE_CLASSES.get(key)
        if name:
            result[name] = enabled
    return result


def filter_ok(drill: NanobotDrillSystemDevice, ore_subtype: str) -> bool:
    wanted = ore_subtype.strip().lower()
    ore_state = raw_ore_state(drill)
    resource_state = raw_resource_state(drill)

    ore_ok = ore_state.get(wanted) is True and all(
        name == wanted or not enabled for name, enabled in ore_state.items()
    )
    resource_ok = resource_state.get("ore") is True and all(
        name == "ore" or not enabled for name, enabled in resource_state.items()
    )
    return ore_ok and resource_ok


def print_filters(drill: NanobotDrillSystemDevice) -> None:
    print("Raw DrillPriorityList:")
    for entry in drill.debug_get_priority_list_raw():
        parsed = parse_priority_entry(entry)
        name = ORE_NAME_BY_HASH.get(parsed[0], "unknown") if parsed else "unknown"
        print(f"  {entry} -> {name}")

    print("Raw ComponentClassList:")
    for entry in drill.debug_get_collect_priority_list_raw():
        parsed = parse_priority_entry(entry)
        name = RESOURCE_CLASSES.get(parsed[0], "unknown") if parsed else "unknown"
        print(f"  {entry} -> {name}")


def configure_collect(
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    timeout: float,
    use_conveyor: bool,
) -> bool:
    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        print(f"  configure attempt {attempt}...")

        hard_stop(drill, hide_area=True)
        run_action(drill, "CollectIfIdle_Off")
        run_action(drill, "TerrainClearingMode_Off")
        safe_set_raw(drill, "Drill.CollectIfIdle", False)
        safe_set_raw(drill, "Drill.TerrainClearingMode", False)
        safe_set_raw(drill, "DrillSystem.CollectIfIdle", False)
        safe_set_raw(drill, "DrillSystem.TerrainClearingMode", False)
        safe_set_raw(drill, "UseConveyor", bool(use_conveyor))
        safe_set_raw(drill, "Drill.UseConveyor", bool(use_conveyor))
        safe_set_raw(drill, "DrillSystem.UseConveyor", bool(use_conveyor))
        safe_set_raw(drill, "Drill.ScriptControlled", True)
        time.sleep(0.4)

        send_collect_filter(drill, ["Ore"])
        time.sleep(0.4)
        send_ore_filter(drill, [ore_subtype], COLLECT_MODE)
        time.sleep(0.6)

        force_collect_mode(drill)
        safe_set_raw(drill, "Drill.ScriptControlled", False)
        time.sleep(0.3)
        run_action(drill, "ScriptControlled_Off")
        time.sleep(0.2)
        force_collect_mode(drill)

        for _ in range(8):
            time.sleep(0.5)
            mode = get_work_mode_raw(drill)
            ok = filter_ok(drill, ore_subtype)
            print(f"    check: WorkMode={mode}, filters_ok={ok}")
            if mode == COLLECT_MODE and ok:
                return True

    print(f"ERROR: Collect + {ore_subtype}-only filter was not confirmed")
    print_filters(drill)
    return False


# ---------------------------------------------------------------------------
# Ore scan helpers
# ---------------------------------------------------------------------------


def extract_ore_name(cell: Dict[str, Any]) -> str:
    for key in ("ore", "Ore", "material", "Material", "materialName", "MaterialName", "minedOre", "MinedOre"):
        value = cell.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if "/" in text:
                text = text.rsplit("/", 1)[-1]
            if "_" in text and text.lower().startswith("stone_"):
                return "Stone"
            return text

    material = cell.get("materialDef") or cell.get("material_def")
    if isinstance(material, dict):
        return extract_ore_name(material)

    return ""


def extract_cell_content(cell: Dict[str, Any]) -> float:
    for key in ("content", "Content", "amount", "Amount", "value", "Value"):
        value = cell.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return 0.0


def extract_cell_position(cell: Dict[str, Any]) -> Optional[Vector]:
    for key in ("position", "Position", "pos", "Pos", "center", "Center", "world", "World"):
        if key in cell:
            point = point_from_any(cell.get(key))
            if point is not None:
                return point

    if {"x", "y", "z"}.issubset(cell.keys()):
        return point_from_any(cell)

    return None


def scan_ore_points(
    grid: Grid,
    ore_subtype: str,
    radius: float,
    timeout: float,
) -> List[Dict[str, Any]]:
    detectors = grid.find_devices_by_type(OreDetectorDevice)
    if not detectors:
        raise RuntimeError("No OreDetectorDevice found on grid")

    detector = detectors[0]
    print(f"Radar: {detector.name} (id={detector.device_id})")
    print(f"Scanning voxels: ore_only=True, radius={radius:g}m, timeout={timeout:g}s")

    detector.scan_and_wait(radius=radius, ore_only=True, timeout=timeout)
    time.sleep(1.0)

    cells = detector.ore_cells()
    print(f"Scan returned ore cells: {len(cells)}")

    wanted = normalize_text(ore_subtype)
    result: List[Dict[str, Any]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue

        ore_name = extract_ore_name(cell)
        if normalize_text(ore_name) != wanted:
            continue

        position = extract_cell_position(cell)
        if position is None:
            continue

        result.append(
            {
                "ore": ore_name,
                "position": position,
                "content": extract_cell_content(cell),
                "raw": cell,
            }
        )

    unique: Dict[Tuple[float, float, float], Dict[str, Any]] = {}
    for item in result:
        position = item["position"]
        key = (round(position[0], 3), round(position[1], 3), round(position[2], 3))
        old = unique.get(key)
        if old is None or item["content"] > old["content"]:
            unique[key] = item

    points = list(unique.values())
    print(f"Filtered {ore_subtype} points: {len(points)}")
    return points


# ---------------------------------------------------------------------------
# Navigation and area helpers
# ---------------------------------------------------------------------------


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
) -> Tuple[Vector, Vector, Vector, Vector]:
    rc.update()
    time.sleep(0.3)
    rc.update()

    telemetry = rc.telemetry or {}
    rc_pos_raw = telemetry.get("position", {})
    orient = telemetry.get("orientation", {})

    if not rc_pos_raw or not orient:
        raise RuntimeError("No Remote Control position/orientation telemetry")

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

    return drill_world, left, up, fwd


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

    safe_set_raw(drill, "Drill.AreaOffsetFrontBack", round(drill_fb, 2))
    time.sleep(delay)
    safe_set_raw(drill, "Drill.AreaOffsetUpDown", round(drill_ud, 2))
    time.sleep(delay)
    safe_set_raw(drill, "Drill.AreaOffsetLeftRight", round(drill_lr, 2))
    time.sleep(delay)

    safe_set_raw(drill, "Drill.AreaWidth", float(area_size))
    time.sleep(delay)
    safe_set_raw(drill, "Drill.AreaHeight", float(area_size))
    time.sleep(delay)
    safe_set_raw(drill, "Drill.AreaDepth", float(area_size))
    time.sleep(delay)

    return drill_fb, drill_ud, drill_lr, v_len(delta)


def point_distance_from(point: Dict[str, Any], origin: Vector) -> float:
    return v_len(v_sub(point["position"], origin))


def ore_density(point: Dict[str, Any], all_points: List[Dict[str, Any]], radius: float) -> int:
    origin = point["position"]
    return sum(1 for other in all_points if v_len(v_sub(origin, other["position"])) <= radius)


def sort_points_by_density(points: List[Dict[str, Any]], drill_world: Vector, density_radius: float) -> List[Dict[str, Any]]:
    scored: List[Tuple[int, float, float, Dict[str, Any]]] = []
    for point in points:
        density = ore_density(point, points, density_radius)
        distance = point_distance_from(point, drill_world)
        content = float(point.get("content", 0) or 0)
        scored.append((density, distance, content, point))

    scored.sort(key=lambda item: (-item[0], item[1], -item[2]))

    result: List[Dict[str, Any]] = []
    for density, _distance, _content, point in scored:
        item = dict(point)
        item["density"] = density
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Mining workflow
# ---------------------------------------------------------------------------


def aim_collect_preflight(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    drill_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    target_world: Vector,
    area_size: float,
    preflight_seconds: float,
    target_dump: int,
    powered_trial_on_wrong_targets: bool,
) -> bool:
    hard_stop(drill, hide_area=True)
    wait_idle(grid, drill, 1.5, "before-point")

    force_collect_mode(drill)
    set_area_to_world_target(drill, drill_world, left, up, fwd, target_world, area_size)
    safe_set_raw(drill, "Drill.ShowArea", True)

    start = time.time()
    best_ore_targets = 0
    best_targets = 0

    while time.time() - start < preflight_seconds:
        time.sleep(0.5)
        force_collect_mode(drill, delay=0.05)
        current, targets, _props = read_targets(drill)
        ore_targets = [target for target in targets if target_has_ore(target, ore_subtype)]
        current_ok = current is not None and current_has_ore(current, targets, ore_subtype)
        best_ore_targets = max(best_ore_targets, len(ore_targets))
        best_targets = max(best_targets, len(targets))
        print(
            f"  preflight: targets={len(targets)}, OreTargets={len(ore_targets)}, "
            f"WorkMode={get_work_mode_raw(drill)}, current={current}"
        )

        if ore_targets or current_ok:
            return True

        if targets and not ore_targets:
            if target_dump > 0:
                dump_targets(targets, ore_subtype, target_dump)
            if powered_trial_on_wrong_targets:
                print(
                    f"  preflight has only non-{ore_subtype} targets, "
                    "but powered inventory trial is enabled"
                )
                return True
            hard_stop(drill, hide_area=True)
            wait_idle(grid, drill, 2.5, "after-bad-preflight")
            print(f"  skip: preflight has only non-{ore_subtype} targets ({len(targets)})")
            return False

    if best_targets == 0:
        print("  preflight has no targets; will try short powered start")
        return True

    print(f"  skip: no {ore_subtype} in preflight, best OreTargets={best_ore_targets}")
    hard_stop(drill, hide_area=True)
    wait_idle(grid, drill, 2.5, "after-empty-preflight")
    return False


def start_powered_collect(
    drill: NanobotDrillSystemDevice,
    drill_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    target_world: Vector,
    area_size: float,
) -> bool:
    force_collect_mode(drill)
    set_area_to_world_target(drill, drill_world, left, up, fwd, target_world, area_size)
    safe_set_raw(drill, "Drill.ShowArea", True)
    run_action(drill, "OnOff_On")
    safe_set_raw(drill, "OnOff", True)
    time.sleep(0.4)

    force_collect_mode(drill)
    set_area_to_world_target(drill, drill_world, left, up, fwd, target_world, area_size)
    time.sleep(0.5)

    mode = get_work_mode_raw(drill)
    if mode != COLLECT_MODE:
        print(f"  BAD MODE after power on: WorkMode={mode}, expected {COLLECT_MODE}")
        hard_stop(drill, hide_area=True)
        return False

    return True


def mine_point(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    amount: float,
    total_baseline_ore: float,
    point_baseline_ore: float,
    point_baseline_stone: float,
    check_interval: float,
    startup_timeout: float,
    no_progress_timeout: float,
    working_point_min_seconds: float,
    stone_safety_delta: float,
    inventory_delta_threshold: float,
    max_stone_per_ore_ratio: float,
    target_dump: int,
    keep_area: bool,
    live_move: bool = False,
) -> int:
    start = time.time()
    last_progress_time = start
    last_total_mined = get_ore_amount(grid, ore_subtype) - total_baseline_ore
    last_point_ore_delta = 0.0
    saw_requested_ore = False
    first_ore_time: Optional[float] = None

    while True:
        time.sleep(max(0.2, check_interval))
        now = time.time()
        elapsed = now - start
        mode = get_work_mode_raw(drill)
        current, targets, _props = read_targets(drill)
        ore_targets = [target for target in targets if target_has_ore(target, ore_subtype)]
        current_ok = current is not None and current_has_ore(current, targets, ore_subtype)

        current_ore_amount = get_ore_amount(grid, ore_subtype)
        mined = current_ore_amount - total_baseline_ore
        point_ore_delta = current_ore_amount - point_baseline_ore
        stone_delta = get_item_amount(grid, "Stone") - point_baseline_stone
        inventory_ok = point_ore_delta >= inventory_delta_threshold

        detected_requested_ore = bool(ore_targets) or current_ok or inventory_ok
        if detected_requested_ore and first_ore_time is None:
            first_ore_time = now
            print(f"  STICKY: {ore_subtype} detected on this point; holding it for at least {working_point_min_seconds:.1f}s")

        saw_requested_ore = saw_requested_ore or detected_requested_ore

        if mined > last_total_mined + 0.01 or point_ore_delta > last_point_ore_delta + 0.01:
            last_progress_time = now
            last_total_mined = mined
            last_point_ore_delta = point_ore_delta

        rate = mined / elapsed if elapsed > 0 else 0.0
        eta = (amount - mined) / rate if rate > 0 and mined < amount else 0.0
        stone_per_ore = stone_delta / point_ore_delta if point_ore_delta > 0.01 else float("inf")
        detector = "target" if (ore_targets or current_ok) else ("inventory" if inventory_ok else "none")

        print(
            f"  [{elapsed:.1f}s] {ore_subtype}: +{mined:.1f}/{amount:.1f}, "
            f"PointOre {point_ore_delta:+.1f}, StonePoint {stone_delta:+.1f}, "
            f"Stone/Ore={stone_per_ore:.3f}, detector={detector}, WorkMode={mode}, "
            f"targets={len(targets)}, OreTargets={len(ore_targets)}, rate={rate:.1f}/s, "
            f"eta={eta:.0f}s, current={current}"
        )

        if mined >= amount:
            print(f"OK: target reached, {ore_subtype} +{mined:.1f}")
            hard_stop(drill, hide_area=not keep_area)
            return 0

        if mode != COLLECT_MODE:
            print(f"SAFETY STOP: WorkMode={mode}, expected {COLLECT_MODE}")
            hard_stop(drill, hide_area=True)
            return 2

        if stone_safety_delta >= 0 and stone_delta > stone_safety_delta:
            print(f"SAFETY STOP: point Stone {stone_delta:+.1f} > +{stone_safety_delta:.1f}")
            hard_stop(drill, hide_area=True)
            return 2

        if max_stone_per_ore_ratio >= 0 and point_ore_delta >= inventory_delta_threshold and stone_delta > 0:
            if stone_per_ore > max_stone_per_ore_ratio:
                print(
                    f"SAFETY STOP: Stone/Ore ratio {stone_per_ore:.3f} > "
                    f"{max_stone_per_ore_ratio:.3f} while inventory shows {ore_subtype}"
                )
                hard_stop(drill, hide_area=True)
                return 2

        if current is not None and not current_ok and not inventory_ok:
            print(f"  WRONG CURRENT TARGET: current target is not {ore_subtype} and inventory has no {ore_subtype} growth: {current}")
            if target_dump > 0 and targets:
                dump_targets(targets, ore_subtype, target_dump)
            # Important: even in live-move mode we must stop here. Otherwise the
            # Nanobot can keep the old Stone target for a few ticks while the
            # script shifts AreaOffset to the next point.
            hard_stop(drill, hide_area=True)
            return 1

        if targets and not ore_targets and not current_ok and not inventory_ok:
            print(f"  only non-{ore_subtype} targets and no inventory growth; stopping before next point")
            if target_dump > 0:
                dump_targets(targets, ore_subtype, target_dump)
            # Live moving over a visible Stone target is unsafe. Stop and let the
            # Nanobot clear its current work before the next AreaOffset shift.
            hard_stop(drill, hide_area=True)
            return 1

        if elapsed >= startup_timeout and not saw_requested_ore and point_ore_delta < inventory_delta_threshold:
            print(f"  no {ore_subtype} by target or inventory after {startup_timeout:.1f}s; next point")
            if not live_move:
                hard_stop(drill, hide_area=True)
            return 1

        if saw_requested_ore and no_progress_timeout > 0 and now - last_progress_time >= no_progress_timeout:
            sticky_elapsed = (now - first_ore_time) if first_ore_time is not None else 0.0
            if first_ore_time is not None and sticky_elapsed < working_point_min_seconds:
                print(
                    f"  STICKY HOLD: no progress for {now - last_progress_time:.1f}s, "
                    f"but point already produced {ore_subtype}; "
                    f"holding {sticky_elapsed:.1f}/{working_point_min_seconds:.1f}s"
                )
                last_progress_time = now
                continue

            print(f"  no progress for {no_progress_timeout:.1f}s after finding {ore_subtype}; next point")
            if not live_move:
                hard_stop(drill, hide_area=True)
            return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan and mine a requested ore with Nanobot Drill safety guards")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--ore", default="Platinum", help="Ore subtype: Platinum, Uranium, Gold, Nickel, Ice, ...")
    parser.add_argument("--amount", type=float, required=True, help="Target ore delta to mine")
    parser.add_argument("--drill-name", default=None, help="Optional Nanobot Drill name substring")
    parser.add_argument("--scan-radius", type=float, default=500.0, help="Ore detector scan radius")
    parser.add_argument("--scan-timeout", type=float, default=45.0, help="Ore detector scan timeout")
    parser.add_argument("--area-size", type=float, default=8.0, help="Nanobot area width/height/depth")
    parser.add_argument("--density-radius", type=float, default=20.0, help="Radius used to prefer internal ore points")
    parser.add_argument("--max-points", type=int, default=120, help="Max dense points to try; 0 means all")
    parser.add_argument("--preflight-seconds", type=float, default=3.0, help="ShowArea-only target check before OnOff")
    parser.add_argument("--startup-timeout", type=float, default=12.0, help="Powered wait per point before moving on")
    parser.add_argument("--no-progress-timeout", type=float, default=60.0, help="Move to next point after N seconds without ore growth")
    parser.add_argument("--working-point-min-seconds", type=float, default=180.0, help="After this point produces ore, keep trying it for at least N seconds unless safety limits are exceeded")
    parser.add_argument("--check-interval", type=float, default=0.5, help="Mining check interval")
    parser.add_argument("--filter-timeout", type=float, default=35.0, help="Filter confirmation timeout")
    parser.add_argument("--stone-safety-delta", type=float, default=5.0, help="Stop if per-point Stone grows above this delta; -1 disables")
    parser.add_argument("--inventory-delta-threshold", type=float, default=1.0, help="Treat ore inventory growth above this value as proof that the point works")
    parser.add_argument("--max-stone-per-ore-ratio", type=float, default=0.05, help="Stop if Stone delta / ore delta exceeds this ratio after ore starts; -1 disables")
    parser.add_argument("--powered-trial-on-wrong-targets", action="store_true", help="Try a short powered inventory-delta probe even when preflight shows only wrong targets")
    parser.add_argument("--live-move", action="store_true", help="Keep Nanobot powered while shifting AreaOffset between points. Skips normal power-off/preflight between points and relies on inventory growth plus safety guards.")
    parser.add_argument("--move-settle-seconds", type=float, default=0.5, help="Small delay after live area movement before inventory monitoring starts")
    parser.add_argument("--target-dump", type=int, default=5, help="How many targets to print on wrong target diagnostics")
    parser.add_argument("--settle-seconds", type=float, default=4.0, help="Initial cooldown after stopping the drill")
    parser.add_argument("--keep-area", action="store_true", help="Keep Nanobot area visible after successful finish")
    parser.add_argument("--no-conveyor", action="store_true", help="Disable conveyor while mining; normally keep it enabled")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        ore_subtype = canonical_ore_name(args.ore)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.amount <= 0:
        print("ERROR: --amount must be > 0")
        return 1
    if args.area_size <= 0:
        print("ERROR: --area-size must be > 0")
        return 1
    if args.scan_radius <= 0:
        print("ERROR: --scan-radius must be > 0")
        return 1
    if args.density_radius <= 0:
        print("ERROR: --density-radius must be > 0")
        return 1
    if args.inventory_delta_threshold < 0:
        print("ERROR: --inventory-delta-threshold must be >= 0")
        return 1

    grid = Grid.from_name(args.grid)
    drill = find_drill(grid, args.drill_name)
    rc = find_remote_control(grid)

    print(f"Grid: {grid.name} (id={grid.grid_id})")
    print(f"Drill: {drill.name} (id={drill.device_id})")
    print(f"RC: {rc.name} (id={rc.device_id})")
    print(f"Ore: {ore_subtype}")
    print(f"Target delta: +{args.amount:.1f}")

    print("\n=== STEP 0: stop and settle ===")
    hard_stop(drill, hide_area=True)
    wait_idle(grid, drill, args.settle_seconds, "initial")

    print(f"\n=== STEP 1: scan {ore_subtype} ===")
    points = scan_ore_points(grid, ore_subtype, radius=args.scan_radius, timeout=args.scan_timeout)
    if not points:
        print(f"ERROR: no {ore_subtype} points found")
        return 2

    print("\n=== STEP 2: navigation frame ===")
    drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)
    points = sort_points_by_density(points, drill_world, args.density_radius)
    if args.max_points > 0:
        points = points[: args.max_points]

    print(f"Selected dense points: {len(points)}")
    for index, point in enumerate(points[:15], start=1):
        print(
            f"  #{index:02d}: density={point.get('density', 0):3d}, "
            f"dist={point_distance_from(point, drill_world):.1f}m, "
            f"content={point.get('content', 0):.1f}, pos={format_point(point['position'])}"
        )

    print(f"\n=== STEP 3: configure Collect + {ore_subtype}-only ===")
    if not configure_collect(drill, ore_subtype, timeout=args.filter_timeout, use_conveyor=not args.no_conveyor):
        return 3

    print("Filters and WorkMode confirmed")
    print_filters(drill)

    total_baseline_ore = get_ore_amount(grid, ore_subtype)
    print(f"\nBaseline {ore_subtype}: {total_baseline_ore:.1f}")
    print(f"Current Stone: {get_item_amount(grid, 'Stone'):.1f}")

    print("\n=== STEP 4: aim and mine ===")
    for index, point in enumerate(points, start=1):
        already_mined = get_ore_amount(grid, ore_subtype) - total_baseline_ore
        if already_mined >= args.amount:
            print(f"OK: target already reached, {ore_subtype} +{already_mined:.1f}")
            hard_stop(drill, hide_area=not args.keep_area)
            return 0

        target_world: Vector = point["position"]
        print(
            f"\n--- Point {index}/{len(points)}: density={point.get('density', 0)}, "
            f"pos={format_point(target_world)} ---"
        )

        if args.live_move:
            print("  LIVE MOVE: moving AreaOffset while Nanobot remains powered")
            force_collect_mode(drill)
            set_area_to_world_target(drill, drill_world, left, up, fwd, target_world, args.area_size)
            safe_set_raw(drill, "Drill.ShowArea", True)
            run_action(drill, "OnOff_On")
            safe_set_raw(drill, "OnOff", True)
            force_collect_mode(drill)
            # WorkMode can reset AreaOffset, so always set the area again after forcing Collect.
            set_area_to_world_target(drill, drill_world, left, up, fwd, target_world, args.area_size)
            if args.move_settle_seconds > 0:
                time.sleep(args.move_settle_seconds)
        else:
            if not aim_collect_preflight(
                grid=grid,
                drill=drill,
                ore_subtype=ore_subtype,
                drill_world=drill_world,
                left=left,
                up=up,
                fwd=fwd,
                target_world=target_world,
                area_size=args.area_size,
                preflight_seconds=args.preflight_seconds,
                target_dump=args.target_dump,
                powered_trial_on_wrong_targets=args.powered_trial_on_wrong_targets,
            ):
                continue

            if not start_powered_collect(drill, drill_world, left, up, fwd, target_world, args.area_size):
                wait_idle(grid, drill, 3.0, "after-bad-start")
                continue

        point_baseline_ore = get_ore_amount(grid, ore_subtype)
        point_baseline_stone = get_item_amount(grid, "Stone")

        result = mine_point(
            grid=grid,
            drill=drill,
            ore_subtype=ore_subtype,
            amount=args.amount,
            total_baseline_ore=total_baseline_ore,
            point_baseline_ore=point_baseline_ore,
            point_baseline_stone=point_baseline_stone,
            check_interval=args.check_interval,
            startup_timeout=args.startup_timeout,
            no_progress_timeout=args.no_progress_timeout,
            working_point_min_seconds=args.working_point_min_seconds,
            stone_safety_delta=args.stone_safety_delta,
            inventory_delta_threshold=args.inventory_delta_threshold,
            max_stone_per_ore_ratio=args.max_stone_per_ore_ratio,
            target_dump=args.target_dump,
            keep_area=args.keep_area,
            live_move=args.live_move,
        )

        if args.live_move:
            if args.move_settle_seconds > 0:
                time.sleep(args.move_settle_seconds)
        else:
            wait_idle(grid, drill, 3.0, "after-point")

        if result == 0:
            return 0
        if result == 1:
            # In safe live-move mode result=1 can mean that a wrong Stone target
            # appeared and was stopped. Always wait until old targets settle
            # before moving the area again.
            wait_idle(grid, drill, 2.5 if args.live_move else 3.0, "after-point")
            continue
        if result == 2:
            print("ERROR: safety stop. The run was stopped to avoid cargo pollution.")
            return 4

    final_mined = get_ore_amount(grid, ore_subtype) - total_baseline_ore
    print(f"ERROR: no dense {ore_subtype} point could be mined safely. Mined +{final_mined:.1f}/{args.amount:.1f}")
    hard_stop(drill, hide_area=True)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
