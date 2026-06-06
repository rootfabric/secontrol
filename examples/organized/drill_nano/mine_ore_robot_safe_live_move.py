#!/usr/bin/env python3
"""Sticky robot-grade Nanobot ore miner for Space Engineers.

The script performs a full mining cycle in one command:
  1. Stop the Nanobot and wait until old work settles.
  2. Scan ore cells with OreDetectorDevice.scan_and_wait(ore_only=True).
  3. Pick candidate points of the requested ore cluster; default is surface/near-first for Collect mode.
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
import subprocess
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


def format_vec_short(point: Vector) -> str:
    return f"({point[0]:+.3f},{point[1]:+.3f},{point[2]:+.3f})"


def gps_line(name: str, point: Vector) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9А-Яа-я_. -]+", "_", name).strip() or "NanobotPoint"
    return f"GPS:{safe_name}:{point[0]:.3f}:{point[1]:.3f}:{point[2]:.3f}:#FF75C9F1:"


def safe_filename_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    text = text.strip("._-")
    return text or "value"


def default_scan_gps_file(grid_name: str, ore_subtype: str) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"nanodrill_scan_gps_{safe_filename_part(grid_name)}_{safe_filename_part(ore_subtype)}_{timestamp}.txt"
    return os.path.abspath(name)


def build_scan_gps_lines(points: List[Dict[str, Any]], ore_subtype: str, limit: int = 0) -> List[str]:
    selected = points if limit <= 0 else points[:limit]
    lines: List[str] = []
    for index, point in enumerate(selected, start=1):
        position = point["position"]
        density = int(point.get("density", 0) or 0)
        content = float(point.get("content", 0) or 0)
        distance = point.get("distance")
        if distance is None:
            name = f"Ore {ore_subtype} {index:03d} d{density} c{content:.0f}"
        else:
            name = f"Ore {ore_subtype} {index:03d} d{density} {float(distance):.0f}m c{content:.0f}"
        lines.append(gps_line(name, position))
    return lines


def write_scan_gps_markers(
    points: List[Dict[str, Any]],
    ore_subtype: str,
    grid_name: str,
    output_file: Optional[str],
    limit: int,
    console_limit: int,
    copy_clipboard: bool,
) -> Optional[str]:
    if not points:
        print("Scan GPS markers: no points to export")
        return None

    lines = build_scan_gps_lines(points, ore_subtype, limit=limit)
    if not lines:
        print("Scan GPS markers: no lines produced")
        return None

    path = os.path.abspath(output_file) if output_file else default_scan_gps_file(grid_name, ore_subtype)
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines))
            handle.write("\n")
    except OSError as exc:
        print(f"WARNING: failed to write scan GPS markers to {path}: {exc}")
        path = None

    print("\n=== SCAN GPS MARKERS ===")
    print(f"GPS markers exported: {len(lines)} point(s) for {ore_subtype}")
    if path:
        print(f"GPS marker file: {path}")
    print("Copy these GPS lines into Space Engineers GPS if you want to visually verify ore scan points.")

    shown = lines if console_limit <= 0 else lines[:console_limit]
    for line in shown:
        print(line)
    if console_limit > 0 and len(lines) > console_limit:
        print(f"... {len(lines) - console_limit} more GPS lines in file")

    if copy_clipboard:
        text = "\r\n".join(lines) + "\r\n"
        copied = False
        for command in (["clip.exe"], ["clip"]):
            try:
                subprocess.run(command, input=text, text=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                copied = True
                break
            except Exception:
                continue
        if copied:
            print("GPS markers copied to clipboard")
        else:
            print("WARNING: failed to copy GPS markers to clipboard; use the file or console lines instead")

    print("=== END SCAN GPS MARKERS ===\n")
    return path


def create_ingame_gps_marker(
    grid: Grid,
    *,
    name: str,
    position: Vector,
    description: str = "",
    show_on_hud: bool = True,
    color_rgb: Tuple[int, int, int] = (117, 201, 241),
) -> int:
    """Create a real in-game GPS marker through the grid command channel.

    The older text export only prints ``GPS:...`` lines; it does not create GPS
    entries in Space Engineers. This helper publishes the plugin command that
    calls ``MyAPIGateway.Session.GPS.AddGps`` for the current player.
    """

    rgb = {"r": int(color_rgb[0]), "g": int(color_rgb[1]), "b": int(color_rgb[2])}

    if hasattr(grid, "create_gps_marker"):
        return grid.create_gps_marker(
            name=name,
            coordinates=position,
            description=description,
            rgb=rgb,
            show_on_hud=show_on_hud,
            show_on_terminal=True,
            show_on_map=True,
            temporary=False,
            always_visible=False,
        )

    # Fallback for older secontrol versions that do not yet expose
    # Grid.create_gps_marker(), but still can publish raw grid commands.
    payload = {
        "name": name,
        "description": description,
        "position": {"x": position[0], "y": position[1], "z": position[2]},
        "rgb": rgb,
        "showOnHud": bool(show_on_hud),
        "showOnTerminal": True,
        "showOnMap": True,
        "temporary": False,
        "alwaysVisible": False,
    }
    return grid.send_grid_command("create_gps", payload=payload)


def publish_scan_gps_markers_to_game(
    grid: Grid,
    points: List[Dict[str, Any]],
    ore_subtype: str,
    *,
    limit: int,
    prefix: str,
    show_on_hud: bool,
    clear_old: bool,
    command_delay: float,
) -> int:
    """Create real in-game GPS markers for scan points.

    This uses the DedicatedPlugin grid-level ``create_gps`` command. The result
    is asynchronous: a positive publish count means the command was sent to
    Redis, then the dedicated server should create the marker on its game thread.
    """

    if not points:
        print("In-game GPS markers: no points to publish")
        return 0

    selected = points if limit <= 0 else points[:limit]
    clean_prefix = re.sub(r"[^A-Za-z0-9А-Яа-я_. -]+", "_", str(prefix or "OreScan")).strip() or "OreScan"
    mask = f"{clean_prefix} {ore_subtype}"

    print("\n=== CREATE IN-GAME GPS MARKERS ===")
    print(f"In-game GPS marker prefix: {mask}")
    print(f"In-game GPS marker count: {len(selected)}")
    print(f"Show on HUD: {show_on_hud}")

    if clear_old:
        try:
            sent = grid.send_grid_command("delete_gps", payload={"mask": mask})
            print(f"Old GPS cleanup command sent: mask='{mask}', publish_count={sent}")
            if command_delay > 0:
                time.sleep(command_delay)
        except Exception as exc:
            print(f"WARNING: failed to send old GPS cleanup command: {exc}")

    published = 0
    for index, point in enumerate(selected, start=1):
        position = point["position"]
        density = int(point.get("density", 0) or 0)
        content = float(point.get("content", 0) or 0)
        distance = point.get("distance")
        if distance is None:
            distance_text = "distNA"
        else:
            distance_text = f"{float(distance):.0f}m"
        name = f"{mask} {index:03d} d{density} {distance_text}"
        desc = f"Nanobot ore scan marker: ore={ore_subtype}, density={density}, content={content:.1f}, pos={position[0]:.3f} {position[1]:.3f} {position[2]:.3f}"
        try:
            count = create_ingame_gps_marker(
                grid,
                name=name,
                position=position,
                description=desc,
                show_on_hud=show_on_hud,
            )
            published += int(count or 0)
            print(f"  GPS create #{index:03d}: publish_count={count}, name='{name}', pos={format_point(position)}")
        except Exception as exc:
            print(f"  WARNING: failed to publish GPS #{index:03d}: {exc}")
        if command_delay > 0:
            time.sleep(command_delay)

    print(f"In-game GPS create commands published: {published}")
    print("If markers do not appear, check that the DedicatedPlugin supports grid command create_gps and that the script uses the correct player_id/owner identity.")
    print("=== END CREATE IN-GAME GPS MARKERS ===\n")
    return published


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

    # Conservative fallback for older telemetry where type_id was missing.
    # This still rejects Iron Ingot / components above, so refinery output no
    # longer looks like newly mined ore.
    if subtype == wanted and (" ore" in display or display == wanted or wanted == "ice"):
        return True
    if f"{wanted} ore" in display:
        return True

    return False


def get_ore_amount(grid: Grid, ore_subtype: str) -> float:
    """Return only raw ore amount, never ingots/components.

    The old version matched any item whose subtype/display contained the ore
    name. For Iron it also counted Iron Ingot, so a refinery could make the
    script think that ore was appearing while raw ore was actually being
    consumed.
    """
    wanted = ore_subtype.strip().lower()
    total = 0.0

    for item in grid.get_all_grid_items():
        if not isinstance(item, dict):
            continue
        if _looks_like_ore_item(item, wanted):
            total += float(item.get("amount", 0) or 0)

    return total


class PositiveOreDeltaCounter:
    """Accumulate gross positive raw-ore inventory deltas.

    Refineries can consume existing ore while the miner is running. Therefore
    `current_amount - baseline` is not a reliable mined amount. This counter
    adds only positive raw-ore steps and ignores negative steps caused by
    refining/conveyor movement.
    """

    def __init__(self, grid: Grid, ore_subtype: str) -> None:
        self.grid = grid
        self.ore_subtype = ore_subtype
        self.last_amount = get_ore_amount(grid, ore_subtype)
        self.total_positive = 0.0
        self.last_step = 0.0
        self.point_start_total = 0.0
        self.point_start_amount = self.last_amount

    def start_point(self) -> None:
        self.last_amount = get_ore_amount(self.grid, self.ore_subtype)
        self.last_step = 0.0
        self.point_start_total = self.total_positive
        self.point_start_amount = self.last_amount

    def update(self) -> Tuple[float, float, float, float]:
        current = get_ore_amount(self.grid, self.ore_subtype)
        step = current - self.last_amount
        self.last_amount = current
        self.last_step = step
        if step > 0.01:
            self.total_positive += step
        return current, step, self.total_positive, self.total_positive - self.point_start_total


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


def score_point_candidates(
    points: List[Dict[str, Any]],
    drill_world: Vector,
    density_radius: float,
) -> List[Dict[str, Any]]:
    """Attach density/distance/surface diagnostics to ore scan points."""
    result: List[Dict[str, Any]] = []
    for point in points:
        item = dict(point)
        density = ore_density(point, points, density_radius)
        distance = point_distance_from(point, drill_world)
        content = float(point.get("content", 0) or 0)
        item["density"] = density
        item["distance"] = distance
        item["content"] = content
        result.append(item)
    return result


def sort_points_by_strategy(
    points: List[Dict[str, Any]],
    drill_world: Vector,
    density_radius: float,
    strategy: str,
    min_density: int = 0,
    near_first_distance: float = 0.0,
) -> List[Dict[str, Any]]:
    """Sort ore scan points for Nanobot Collect mode.

    v19 change: sparse detector islands are not only de-prioritized, they are
    removed from the candidate list while there are any viable cells that pass
    ``--min-point-density``. The 180-degree ship turn logs showed the exact
    failure mode: a density=2 point at 147.9m was tried before a density=6
    point at 152.1m because it barely fell inside ``--near-first-distance``.
    The AreaOffset math then aimed correctly at a bad GPS point in open space.
    
    With the default ``--min-point-density 6`` the sparse point is skipped and
    the first attempted point is the nearby usable cluster. If a deposit is
    genuinely tiny and no point reaches the density threshold, the script falls
    back to all points instead of failing the scan.
    """
    scored = score_point_candidates(points, drill_world, density_radius)
    strategy = (strategy or "surface").strip().lower()
    min_density = max(0, int(min_density or 0))

    if min_density > 0:
        viable = [point for point in scored if int(point.get("density", 0)) >= min_density]
        if viable:
            scored = viable

    def near_tier(point: Dict[str, Any]) -> int:
        if near_first_distance <= 0:
            return 0
        return 0 if float(point.get("distance", 0) or 0) <= near_first_distance else 1

    if strategy == "density":
        scored.sort(key=lambda point: (near_tier(point), -int(point.get("density", 0)), float(point.get("distance", 0)), -float(point.get("content", 0) or 0)))
    elif strategy == "nearest":
        scored.sort(key=lambda point: (near_tier(point), float(point.get("distance", 0)), -int(point.get("density", 0)), -float(point.get("content", 0) or 0)))
    elif strategy == "surface":
        scored.sort(key=lambda point: (near_tier(point), float(point.get("distance", 0)), -min(int(point.get("density", 0)), 16), -float(point.get("content", 0) or 0)))
    else:
        raise ValueError("Unknown point strategy %r. Use density, nearest, or surface." % strategy)

    return scored

def sort_points_by_density(points: List[Dict[str, Any]], drill_world: Vector, density_radius: float) -> List[Dict[str, Any]]:
    return sort_points_by_strategy(points, drill_world, density_radius, "density")


def print_point_strategy_preview(
    points: List[Dict[str, Any]],
    drill_world: Vector,
    density_radius: float,
    limit: int,
    min_density: int = 0,
    near_first_distance: float = 0.0,
) -> None:
    if limit <= 0 or not points:
        return
    print("Point strategy preview:")
    if min_density > 0:
        scored_preview = score_point_candidates(points, drill_world, density_radius)
        viable_count = sum(1 for point in scored_preview if int(point.get("density", 0)) >= min_density)
        print(f"  viable density threshold: >= {min_density} same-ore cells within radius {density_radius:g}m; viable={viable_count}/{len(scored_preview)}")
        if viable_count == 0:
            print("  density threshold has no matching points, so sparse points remain enabled as fallback")
        else:
            print(f"  sparse scan cells below density {min_density} are excluded from mining candidates: skipped={len(scored_preview) - viable_count}")
    if near_first_distance > 0:
        scored_preview = score_point_candidates(points, drill_world, density_radius)
        near_count = sum(1 for point in scored_preview if float(point.get("distance", 0) or 0) <= near_first_distance)
        print(f"  near-first distance: <= {near_first_distance:g}m; near={near_count}/{len(scored_preview)}")
        if near_count == 0:
            print("  no nearby scan cells inside near-first distance; falling back to normal strategy order")
    for strategy in ("surface", "nearest", "density"):
        preview = sort_points_by_strategy(points, drill_world, density_radius, strategy, min_density=min_density, near_first_distance=near_first_distance)[:limit]
        print(f"  {strategy}:")
        for index, point in enumerate(preview, start=1):
            print(
                f"    #{index:02d}: dist={float(point.get('distance', point_distance_from(point, drill_world))):7.1f}m "
                f"density={int(point.get('density', 0)):3d} content={float(point.get('content', 0) or 0):6.1f} "
                f"pos={format_point(point['position'])}"
            )

def debug_area_against_scan_points(
    points: List[Dict[str, Any]],
    center_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    area_size: float,
    max_rows: int,
) -> None:
    """Print how scan cells lie inside the requested Nanobot area cube.

    This does not rely on Nanobot target telemetry. It only checks the geometry:
    if many ore scan cells are inside the intended cube, but Nanobot targets=0,
    the problem is usually not AreaOffset math but one of these:
      - ore is buried and Collect mode cannot reach it yet;
      - Nanobot target scan range/shape differs from OreDetector scan cells;
      - the plugin's area.center/visual area is stale or uses a different origin.
    """
    if not points:
        return

    half = float(area_size) * 0.5
    rows: List[Tuple[float, bool, float, float, float, float, Dict[str, Any]]] = []
    inside_count = 0
    near_shell_count = 0
    min_lr = min_ud = min_fb = float("inf")
    max_lr = max_ud = max_fb = float("-inf")

    for point in points:
        pos = point["position"]
        delta = v_sub(pos, center_world)
        lr = v_dot(delta, left)
        ud = v_dot(delta, up)
        fb = v_dot(delta, fwd)
        min_lr, max_lr = min(min_lr, lr), max(max_lr, lr)
        min_ud, max_ud = min(min_ud, ud), max(max_ud, ud)
        min_fb, max_fb = min(min_fb, fb), max(max_fb, fb)
        local_max = max(abs(lr), abs(ud), abs(fb))
        inside = local_max <= half + 1e-6
        if inside:
            inside_count += 1
        if local_max <= half + 5.0:
            near_shell_count += 1
        rows.append((v_len(delta), inside, local_max, lr, ud, fb, point))

    rows.sort(key=lambda item: (not item[1], item[0]))

    print(
        "  Area/scan geometry check: "
        f"center=({center_world[0]:.2f}, {center_world[1]:.2f}, {center_world[2]:.2f}), "
        f"size={area_size:.1f}, half={half:.1f}; "
        f"scan_points_inside={inside_count}/{len(points)}, "
        f"inside_or_5m_shell={near_shell_count}/{len(points)}"
    )
    print(f"  GPS area center: {gps_line('Nanobot area requested center', center_world)}")
    print(
        "  Scan cloud local bounds relative to requested center: "
        f"LR=[{min_lr:+.1f},{max_lr:+.1f}] UD=[{min_ud:+.1f},{max_ud:+.1f}] FB=[{min_fb:+.1f},{max_fb:+.1f}]"
    )
    print("  Nearest/inside scan cells in Nanobot-area local coordinates:")
    for row_index, (dist, inside, local_max, lr, ud, fb, point) in enumerate(rows[:max(0, max_rows)], start=1):
        mark = "INSIDE" if inside else "outside"
        print(
            f"    #{row_index:02d} {mark:7s} dist={dist:7.2f}m maxAxis={local_max:7.2f}m "
            f"local LR={lr:+8.2f} UD={ud:+8.2f} FB={fb:+8.2f} "
            f"density={point.get('density', 0):3d} content={float(point.get('content', 0) or 0):6.1f} "
            f"pos={format_point(point['position'])}"
        )
        if row_index <= 3:
            print(f"       GPS scan cell: {gps_line('Nanobot scan cell %02d' % row_index, point['position'])}")




def _read_number_from_dict(data: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key in data:
            try:
                return float(data.get(key))
            except (TypeError, ValueError):
                pass
    return None


def print_current_area_vs_scan_diagnostic(
    drill: NanobotDrillSystemDevice,
    points: List[Dict[str, Any]],
    *,
    max_rows: int = 8,
) -> None:
    """Show where the currently visible Nanobot area is relative to scan cells.

    This is useful after a manual terminal adjustment. If the user manually puts
    the cube onto ore, this block should show the current area center very close
    to one of the GPS scan points. It also exposes when the script is simply
    choosing a farther scan cluster, not calculating the AreaOffset incorrectly.
    """
    if not points:
        return
    try:
        drill.wait_for_telemetry(timeout=2.0, wait_for_new=True, need_update=True)
    except Exception:
        try:
            drill.update()
            time.sleep(0.15)
        except Exception:
            pass

    telemetry = drill.telemetry or {}
    area = telemetry.get("area") if isinstance(telemetry.get("area"), dict) else {}
    props = telemetry.get("properties", {}) if isinstance(telemetry.get("properties"), dict) else {}
    center = point_from_any(area.get("center") or area.get("Center"))
    fb = _read_number_from_dict(area, "offsetFrontBack", "frontBack", "FrontBack")
    ud = _read_number_from_dict(area, "offsetUpDown", "upDown", "UpDown")
    lr = _read_number_from_dict(area, "offsetLeftRight", "leftRight", "LeftRight")
    if fb is None:
        fb = _read_number_from_dict(props, "Drill.AreaOffsetFrontBack", "AreaOffsetFrontBack")
    if ud is None:
        ud = _read_number_from_dict(props, "Drill.AreaOffsetUpDown", "AreaOffsetUpDown")
    if lr is None:
        lr = _read_number_from_dict(props, "Drill.AreaOffsetLeftRight", "AreaOffsetLeftRight")

    print("\n=== CURRENT NANOBOT AREA VS SCAN DIAGNOSTIC ===")
    print(
        "Current terminal offsets: "
        f"X/LR={lr if lr is not None else 'NA'}, "
        f"Y/UD={ud if ud is not None else 'NA'}, "
        f"Z/FB={fb if fb is not None else 'NA'}"
    )
    if center is None:
        print("Current area center is not present in Nanobot telemetry")
        print("=== END CURRENT NANOBOT AREA VS SCAN DIAGNOSTIC ===\n")
        return

    print(f"Current reported area center: {format_point(center)}")
    nearest = sorted(points, key=lambda point: v_len(v_sub(point["position"], center)))[:max(1, max_rows)]
    print("Nearest scan cells to current reported area center:")
    for index, point in enumerate(nearest, start=1):
        distance = v_len(v_sub(point["position"], center))
        print(
            f"  #{index:02d}: dist={distance:7.2f}m density={int(point.get('density', 0)):3d} "
            f"scan_dist={float(point.get('distance', 0) or 0):7.1f}m "
            f"content={float(point.get('content', 0) or 0):6.1f} pos={format_point(point['position'])}"
        )
    print("=== END CURRENT NANOBOT AREA VS SCAN DIAGNOSTIC ===\n")


def warn_if_selected_far_from_nearest(points: List[Dict[str, Any]]) -> None:
    if len(points) < 2:
        return
    first = points[0]
    nearest = min(points, key=lambda point: float(point.get("distance", 0) or 0))
    first_dist = float(first.get("distance", 0) or 0)
    nearest_dist = float(nearest.get("distance", 0) or 0)
    if first is not nearest and first_dist > nearest_dist + 25.0:
        print("\nWARNING: selected first scan point is not the nearest ore point.")
        print(
            f"  selected: dist={first_dist:.1f}m density={int(first.get('density', 0))} "
            f"pos={format_point(first['position'])}"
        )
        print(
            f"  nearest:  dist={nearest_dist:.1f}m density={int(nearest.get('density', 0))} "
            f"pos={format_point(nearest['position'])}"
        )
        print(
            "  If the ship is parked next to ore, use --point-strategy nearest "
            "or keep the v15 defaults. Dense far clusters can look like a coordinate bug."
        )

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
        print("  DEBUG HINT: geometry can be correct while Collect still sees targets=0. This point may be stale/open-space from the ore detector map or buried behind stone. The script will switch to another scan point and skip nearby empty-cluster points.")
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
    ore_counter: PositiveOreDeltaCounter,
    point_baseline_stone: float,
    check_interval: float,
    startup_timeout: float,
    empty_powered_timeout: float,
    target_no_ore_timeout: float,
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
    last_total_mined = ore_counter.total_positive
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

        current_ore_amount, ore_step, mined, point_ore_delta = ore_counter.update()
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

        rate = point_ore_delta / elapsed if elapsed > 0 else 0.0
        eta = (amount - mined) / rate if rate > 0 and mined < amount else 0.0
        stone_per_ore = stone_delta / point_ore_delta if point_ore_delta > 0.01 else float("inf")
        detector = "target" if (ore_targets or current_ok) else ("inventory" if inventory_ok else "none")

        print(
            f"  [{elapsed:.1f}s] {ore_subtype}: mined+{mined:.1f}/{amount:.1f}, "
            f"PointOre+{point_ore_delta:.1f}, OreInv={current_ore_amount:.1f}, OreStep={ore_step:+.1f}, "
            f"StonePoint {stone_delta:+.1f}, "
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

        if (
            empty_powered_timeout > 0
            and elapsed >= empty_powered_timeout
            and not saw_requested_ore
            and point_ore_delta < inventory_delta_threshold
            and not targets
            and current is None
        ):
            print(
                f"  empty point: no targets/current/{ore_subtype} inventory growth "
                f"after {empty_powered_timeout:.1f}s; switching to next scan point"
            )
            if not live_move:
                hard_stop(drill, hide_area=True)
            return 1

        if (
            target_no_ore_timeout > 0
            and elapsed >= target_no_ore_timeout
            and point_ore_delta < inventory_delta_threshold
            and (ore_targets or current_ok)
        ):
            print(
                f"  target visible but no raw {ore_subtype} inventory growth "
                f"after {target_no_ore_timeout:.1f}s; switching to next scan point"
            )
            if target_dump > 0 and targets:
                dump_targets(targets, ore_subtype, target_dump)
            if not live_move:
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



# NANODRILL_DYNAMIC_AREA_FIX
# AreaOffset is Nanobot-block-local. These overrides replace the old fixed
# DRILL_AXIS_MAP logic and use Nanobot position/orientation telemetry.
try:
    from nanodrill_area_frame import (
        get_navigation_frame as _dynamic_get_navigation_frame,
        set_area_to_world_target as _dynamic_set_area_to_world_target,
        drill_offsets_from_local_vector as _dynamic_drill_offsets_from_local_vector,
        grid_vector_from_drill_offsets as _dynamic_grid_vector_from_drill_offsets,
        get_block_local_position as _dynamic_get_block_local_position,
        get_drill_local_offset as _dynamic_get_drill_local_offset,
        get_navigation_frame_candidates as _dynamic_get_navigation_frame_candidates,
    )

    get_navigation_frame = _dynamic_get_navigation_frame
    set_area_to_world_target = _dynamic_set_area_to_world_target
    drill_offsets_from_local_vector = _dynamic_drill_offsets_from_local_vector
    get_block_local_position = _dynamic_get_block_local_position
    get_drill_local_offset = _dynamic_get_drill_local_offset
    get_navigation_frame_candidates = _dynamic_get_navigation_frame_candidates
    try:
        grid_vector_from_drill_offsets = _dynamic_grid_vector_from_drill_offsets
    except NameError:
        pass
except Exception as _dynamic_area_import_error:
    print(f"WARNING: dynamic Nanobot area helper unavailable: {_dynamic_area_import_error}")


def point_in_failed_cluster(point: Dict[str, Any], failed_clusters: List[Tuple[Vector, float]]) -> Optional[Tuple[Vector, float, float]]:
    """Return failed cluster info if a scan point should be skipped.

    A powered Nanobot trial with zero targets and no raw-ore growth proves that
    nearby detector cells are not useful for Collect mode right now. Without this
    guard the script can spend several attempts on the same stale/open-space
    detector island before reaching a productive cluster.
    """
    position = point.get("position")
    if position is None:
        return None
    for center, radius in failed_clusters:
        distance = v_len(v_sub(position, center))
        if distance <= radius:
            return center, radius, distance
    return None


def automatic_empty_cluster_skip_radius(area_size: float, density_radius: float, configured_radius: float) -> float:
    if configured_radius and configured_radius > 0:
        return float(configured_radius)
    # Nearly the whole Nanobot cube footprint skips points probably covered by
    # the same failed/stale detector island. density_radius*2 catches 10m detector islands.
    return max(float(area_size) * 0.95, float(density_radius) * 2.0, 30.0)



def ore_visible_now(drill: NanobotDrillSystemDevice, ore_subtype: str) -> Tuple[bool, Any, List[Any], List[Any]]:
    current, targets, _props = read_targets(drill)
    ore_targets = [target for target in targets if target_has_ore(target, ore_subtype)]
    current_ok = current is not None and current_has_ore(current, targets, ore_subtype)
    return bool(ore_targets) or current_ok, current, targets, ore_targets


def find_candidate_by_label(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice,
    label: str,
    max_candidates: int,
) -> Optional[Tuple[str, Vector, Vector, Vector, Vector]]:
    candidate_func = globals().get("get_navigation_frame_candidates")
    if candidate_func is None:
        return None
    try:
        candidates = candidate_func(grid, drill, rc, max_candidates=0)
    except Exception as exc:
        print(f"  WARNING: failed to rebuild locked AreaOffset candidate '{label}': {exc}")
        return None
    for candidate in candidates:
        if candidate[0] == label:
            return candidate
    return None


def probe_area_axis_candidates(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice,
    ore_subtype: str,
    target_world: Vector,
    area_size: float,
    *,
    powered_seconds: float,
    max_candidates: int,
    initial_label: Optional[str] = None,
    target_dump: int = 0,
) -> Optional[Tuple[str, Vector, Vector, Vector, Vector]]:
    """Empirically find the AreaOffset frame that the Nanobot mod really uses.

    The helper telemetry can be self-consistent while the visible Nanobot cube is
    wrong, because telemetry area.center may be calculated by our plugin formula.
    This probe does not trust area.center. It sets the candidate frame, briefly
    powers the Nanobot in strict Collect mode, then checks real Nanobot target
    telemetry and raw inventory. The first candidate that produces requested ore
    targets/current is the one that matches the mod's visual/working area.
    """
    candidate_func = globals().get("get_navigation_frame_candidates")
    if candidate_func is None:
        print("  Axis probe unavailable: dynamic helper does not expose get_navigation_frame_candidates")
        return None

    try:
        candidates = candidate_func(grid, drill, rc, max_candidates=0)
    except Exception as exc:
        print(f"  Axis probe unavailable: failed to build candidate frames: {exc}")
        return None

    if not candidates:
        print("  Axis probe unavailable: no candidate AreaOffset frames")
        return None

    # Put the previously successful label first if we have one.
    if initial_label:
        candidates.sort(key=lambda candidate: 0 if candidate[0] == initial_label else 1)

    if max_candidates > 0:
        candidates = candidates[:max_candidates]

    print("\n  === REAL NANOBOT AREA AXIS PROBE ===")
    print("  Reason: current mapping produced no real Nanobot targets. The probe will try alternative axis/origin mappings and keep the first one that the mod itself reports as ore target.")
    print(f"  Candidate count: {len(candidates)}; powered_seconds={powered_seconds:.1f}s; target={format_point(target_world)}")

    baseline_ore = get_ore_amount(grid, ore_subtype)
    best_candidate: Optional[Tuple[str, Vector, Vector, Vector, Vector]] = None
    best_score = -1

    for index, candidate in enumerate(candidates, start=1):
        label, origin, lr_axis, ud_axis, fb_axis = candidate
        try:
            hard_stop(drill, hide_area=True)
            force_collect_mode(drill, delay=0.05)
            set_area_to_world_target(drill, origin, lr_axis, ud_axis, fb_axis, target_world, area_size, delay=0.03)
            safe_set_raw(drill, "Drill.ShowArea", True)
            run_action(drill, "OnOff_On")
            safe_set_raw(drill, "OnOff", True)
            time.sleep(max(0.25, powered_seconds))
            force_collect_mode(drill, delay=0.03)
            visible, current, targets, ore_targets = ore_visible_now(drill, ore_subtype)
            ore_now = get_ore_amount(grid, ore_subtype)
            ore_delta = ore_now - baseline_ore
            score = len(ore_targets) * 10 + (5 if visible else 0) + (100 if ore_delta > 0.01 else 0)
            best_score = max(best_score, score)
            print(
                f"  probe #{index:02d}: score={score:3d}, ore_delta={ore_delta:+.1f}, "
                f"targets={len(targets)}, OreTargets={len(ore_targets)}, current={current}, label={label}"
            )
            if target_dump > 0 and targets and not ore_targets:
                dump_targets(targets, ore_subtype, target_dump)
            if visible or ore_delta > 0.01:
                print(f"  AXIS PROBE SUCCESS: {label}")
                best_candidate = candidate
                # Keep the Nanobot on this successful area; caller will continue
                # with the same frame and power cycle as needed.
                return best_candidate
        except Exception as exc:
            print(f"  probe #{index:02d} failed for label={label}: {exc}")
        finally:
            if best_candidate is None:
                hard_stop(drill, hide_area=True)
                time.sleep(0.15)

    print(f"  AXIS PROBE FAILED: no candidate produced {ore_subtype} targets or positive raw-ore delta. best_score={best_score}")
    print("  === END REAL NANOBOT AREA AXIS PROBE ===\n")
    hard_stop(drill, hide_area=True)
    return None

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
    parser.add_argument("--area-debug-points", type=int, default=5, help="Print detailed area/scan geometry diagnostics for first N candidate points; 0 disables")
    parser.add_argument("--area-debug-rows", type=int, default=12, help="How many scan cells to print in each area geometry diagnostic")
    parser.add_argument("--empty-powered-timeout", type=float, default=8.0, help="Fast switch to the next scan point when powered Nanobot sees no targets/current and raw ore inventory does not grow; 0 disables")
    parser.add_argument("--target-no-ore-timeout", type=float, default=15.0, help="Fast switch when Nanobot shows requested ore targets/current but raw ore inventory does not grow; 0 disables")
    parser.add_argument("--refresh-transform-each-point", action=argparse.BooleanOptionalAction, default=True, help="Re-read ship/RC/Nanobot position and Nanobot rotation before every scan point")
    parser.add_argument("--skip-empty-area-neighbors", action=argparse.BooleanOptionalAction, default=True, help="When a powered point has no targets and no ore growth, skip nearby scan points from the same failed area/cluster")
    parser.add_argument("--empty-cluster-skip-radius", type=float, default=0.0, help="Radius in meters for skipping nearby scan points after an empty powered trial; 0 = auto from area-size/density-radius")
    parser.add_argument("--min-point-density", type=int, default=6, help="Prefer scan cells with at least this many same-ore neighbors inside --density-radius. Default 6 rejects sparse/stale near detector cells but still keeps small visible deposits; use 0 for raw nearest-point probing or 10+ for distant dense autonomous mining")
    parser.add_argument("--near-first-distance", type=float, default=150.0, help="Try scan cells within this distance from the Nanobot before farther dense clusters; 0 disables the near-first tier")
    parser.add_argument("--point-strategy", choices=["surface", "nearest", "density"], default="nearest", help="How to choose scan points. v19 filters out sparse detector cells below --min-point-density while viable denser points exist, then applies nearest/near-first ordering")
    parser.add_argument("--point-preview", type=int, default=8, help="Print first N candidate scan cells for surface/nearest/density strategies")
    parser.add_argument("--scan-gps-markers", action=argparse.BooleanOptionalAction, default=False, help="After ore scan, export Space Engineers GPS lines for detected ore candidate points. Default is off to avoid marker/log spam")
    parser.add_argument("--scan-gps-limit", type=int, default=0, help="Max detected ore points to export as GPS markers; 0 means all selected/scored scan points")
    parser.add_argument("--scan-gps-console-limit", type=int, default=25, help="How many GPS lines to print to console; 0 prints all")
    parser.add_argument("--scan-gps-file", default=None, help="Optional output .txt file for scan GPS markers; default is nanodrill_scan_gps_<grid>_<ore>_<timestamp>.txt in current directory")
    parser.add_argument("--scan-gps-copy-clipboard", action="store_true", help="Try to copy exported GPS marker lines to the Windows clipboard via clip.exe")
    parser.add_argument("--scan-gps-create-ingame", action=argparse.BooleanOptionalAction, default=False, help="Create real in-game Space Engineers GPS markers through the DedicatedPlugin create_gps grid command. Default is off; enable only for visual debugging")
    parser.add_argument("--scan-gps-ingame-limit", type=int, default=80, help="Max scan points to create as real in-game GPS markers; 0 means all scored scan points")
    parser.add_argument("--scan-gps-ingame-prefix", default="OreScan", help="Prefix for created in-game GPS marker names. Old markers with '<prefix> <ore>' can be removed before creating new ones")
    parser.add_argument("--scan-gps-ingame-show-on-hud", action=argparse.BooleanOptionalAction, default=True, help="Show created GPS markers on HUD")
    parser.add_argument("--scan-gps-clear-old", action=argparse.BooleanOptionalAction, default=True, help="Before creating in-game GPS markers, delete old GPS markers whose name contains '<prefix> <ore>'")
    parser.add_argument("--scan-gps-command-delay", type=float, default=0.03, help="Small delay between GPS create/delete commands to avoid flooding the command queue")
    parser.add_argument("--axis-probe-on-empty", action=argparse.BooleanOptionalAction, default=False, help="Diagnostic only: if the current AreaOffset mapping produces no Nanobot targets, briefly try alternative axis/origin mappings. Default is off because wrong/far scan point selection was the real cause in v14 logs")
    parser.add_argument("--axis-probe-powered-seconds", type=float, default=1.0, help="Powered Collect wait time per alternative AreaOffset candidate during axis probe")
    parser.add_argument("--axis-probe-max-candidates", type=int, default=32, help="Max alternative AreaOffset axis/origin candidates to probe; 0 means all candidates")
    parser.add_argument("--axis-probe-lock", action=argparse.BooleanOptionalAction, default=True, help="After an axis probe succeeds, reuse the successful mapping label for following points while still refreshing live positions")
    parser.add_argument(
        "--area-axis-mode",
        choices=["auto", "right-up-forward", "left-up-forward", "right-up-backward", "left-up-backward"],
        default="auto",
        help=(
            "Nanobot AreaOffset axis mapping. Default auto uses the real visual mod axis right-up-forward. "
            "Old area.center auto-calibration is disabled because it mirrored LeftRight."
        ),
    )
    parser.add_argument(
        "--area-origin-source",
        choices=["device", "block", "rc-local", "reported-center"],
        default="device",
        help=(
            "AreaOffset origin source. Default device uses Nanobot Block.GetPosition telemetry. "
            "rc-local recomputes Nanobot origin from RC/ship position plus the Nanobot local offset. "
            "reported-center is diagnostic only because old plugin builds computed area.center with the wrong LeftRight sign."
        ),
    )
    parser.add_argument(
        "--area-transform-priority",
        choices=["ship-local", "device", "grid"],
        default="ship-local",
        help=(
            "Which transform is authoritative for AreaOffset axes. Default ship-local calculates real terminal axes "
            "from RC/ship rotation and Nanobot local_orientation, but uses live Nanobot position as origin. "
            "It no longer trusts reported area.center by default because old telemetry mirrored LeftRight."
        ),
    )
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
    if args.empty_powered_timeout < 0:
        print("ERROR: --empty-powered-timeout must be >= 0")
        return 1
    if args.target_no_ore_timeout < 0:
        print("ERROR: --target-no-ore-timeout must be >= 0")
        return 1
    if args.empty_cluster_skip_radius < 0:
        print("ERROR: --empty-cluster-skip-radius must be >= 0")
        return 1
    if args.min_point_density < 0:
        print("ERROR: --min-point-density must be >= 0")
        return 1
    if args.near_first_distance < 0:
        print("ERROR: --near-first-distance must be >= 0")
        return 1
    if args.scan_gps_ingame_limit < 0:
        print("ERROR: --scan-gps-ingame-limit must be >= 0")
        return 1
    if args.scan_gps_command_delay < 0:
        print("ERROR: --scan-gps-command-delay must be >= 0")
        return 1
    if args.axis_probe_powered_seconds < 0:
        print("ERROR: --axis-probe-powered-seconds must be >= 0")
        return 1
    if args.axis_probe_max_candidates < 0:
        print("ERROR: --axis-probe-max-candidates must be >= 0")
        return 1

    # Pass transform diagnostics/config to nanodrill_area_frame without changing
    # the historical get_navigation_frame() function signature used by other scripts.
    os.environ["NANODRILL_AREA_AXIS_MODE"] = args.area_axis_mode
    os.environ["NANODRILL_AREA_ORIGIN_SOURCE"] = args.area_origin_source
    os.environ["NANODRILL_TRANSFORM_PRIORITY"] = args.area_transform_priority
    print(f"Nanobot area axis mode: {args.area_axis_mode}")
    print(f"Nanobot area origin source: {args.area_origin_source}")
    print(f"Nanobot transform priority: {args.area_transform_priority} (v21: ship-local axes, live Nanobot origin; area.center only sanity-checks axis sign)")
    if args.area_axis_mode == "auto":
        print("Nanobot effective area axis mode: auto -> left-up-backward (X/LR=left, Y/UD=up, Z/FB=backward)")
    print(f"Refresh transform each point: {args.refresh_transform_each_point}")
    print(f"Empty powered point timeout: {args.empty_powered_timeout:.1f}s")
    print(f"Visible-target no-ore timeout: {args.target_no_ore_timeout:.1f}s")
    print(f"Min point density preference: {args.min_point_density}")
    if args.min_point_density == 0:
        print("WARNING: --min-point-density=0 allows sparse nearest detector cells to be tried first; use the default 6 for normal mining")
    print(f"Near-first distance: {'disabled' if args.near_first_distance == 0 else str(args.near_first_distance) + 'm'}")
    print(f"Skip empty area neighbors: {args.skip_empty_area_neighbors}; radius={'auto' if args.empty_cluster_skip_radius == 0 else args.empty_cluster_skip_radius}")
    print(f"Real Nanobot axis probe on empty: {args.axis_probe_on_empty}; powered_seconds={args.axis_probe_powered_seconds:.1f}; max_candidates={'all' if args.axis_probe_max_candidates == 0 else args.axis_probe_max_candidates}; lock={args.axis_probe_lock}")

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
    print("Initial transform is used only for point sorting/preview. The live transform is refreshed before each point when enabled.")
    print_point_strategy_preview(points, drill_world, args.density_radius, args.point_preview, min_density=args.min_point_density, near_first_distance=args.near_first_distance)
    scored_points = sort_points_by_strategy(points, drill_world, args.density_radius, args.point_strategy, min_density=args.min_point_density, near_first_distance=args.near_first_distance)
    print_current_area_vs_scan_diagnostic(drill, scored_points, max_rows=8)
    warn_if_selected_far_from_nearest(scored_points)
    if args.scan_gps_markers:
        write_scan_gps_markers(
            scored_points,
            ore_subtype=ore_subtype,
            grid_name=grid.name,
            output_file=args.scan_gps_file,
            limit=max(0, args.scan_gps_limit),
            console_limit=max(0, args.scan_gps_console_limit),
            copy_clipboard=bool(args.scan_gps_copy_clipboard),
        )
    if args.scan_gps_create_ingame:
        publish_scan_gps_markers_to_game(
            grid,
            scored_points,
            ore_subtype=ore_subtype,
            limit=max(0, args.scan_gps_ingame_limit),
            prefix=args.scan_gps_ingame_prefix,
            show_on_hud=bool(args.scan_gps_ingame_show_on_hud),
            clear_old=bool(args.scan_gps_clear_old),
            command_delay=float(args.scan_gps_command_delay),
        )
    points = scored_points
    if args.max_points > 0:
        points = points[: args.max_points]

    print(f"Selected points: {len(points)} using strategy={args.point_strategy}")
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
    ore_counter = PositiveOreDeltaCounter(grid, ore_subtype)
    print(f"\nBaseline raw {ore_subtype} ore: {total_baseline_ore:.1f}")
    print("Mined amount is counted as accumulated positive raw-ore inventory deltas only; ingots/components are ignored.")
    print(f"Current Stone: {get_item_amount(grid, 'Stone'):.1f}")

    failed_clusters: List[Tuple[Vector, float]] = []
    axis_probe_locked_label: Optional[str] = None
    empty_skip_radius = automatic_empty_cluster_skip_radius(
        area_size=args.area_size,
        density_radius=args.density_radius,
        configured_radius=args.empty_cluster_skip_radius,
    )
    print(
        f"Empty point cluster skip radius: {empty_skip_radius:.1f}m "
        f"({'enabled' if args.skip_empty_area_neighbors else 'disabled'})"
    )

    print("\n=== STEP 4: aim and mine ===")
    for index, point in enumerate(points, start=1):
        _current_ore, _ore_step, already_mined, _point_delta = ore_counter.update()
        if already_mined >= args.amount:
            print(f"OK: target already reached, {ore_subtype} +{already_mined:.1f}")
            hard_stop(drill, hide_area=not args.keep_area)
            return 0

        target_world: Vector = point["position"]

        if args.skip_empty_area_neighbors:
            failed_info = point_in_failed_cluster(point, failed_clusters)
            if failed_info is not None:
                failed_center, failed_radius, failed_distance = failed_info
                print(
                    f"\n--- Point {index}/{len(points)} skipped: inside failed empty cluster "
                    f"dist={failed_distance:.1f}m <= {failed_radius:.1f}m; "
                    f"cluster_center={format_point(failed_center)}; point={format_point(target_world)} ---"
                )
                continue

        if args.refresh_transform_each_point:
            print(f"\n--- Refresh live Nanobot transform before point {index}/{len(points)} ---")
            try:
                if axis_probe_locked_label:
                    locked_candidate = find_candidate_by_label(
                        grid,
                        drill,
                        rc,
                        axis_probe_locked_label,
                        max_candidates=max(0, args.axis_probe_max_candidates),
                    )
                    if locked_candidate is not None:
                        _label, drill_world, left, up, fwd = locked_candidate
                        print(f"Using locked real Nanobot AreaOffset frame: {_label}")
                    else:
                        print(f"WARNING: locked AreaOffset frame '{axis_probe_locked_label}' was not found; falling back to normal auto frame")
                        drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)
                else:
                    drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)
            except Exception as exc:
                print(f"ERROR: failed to refresh Nanobot transform before point {index}: {exc}")
                hard_stop(drill, hide_area=True)
                return 4

        print(
            f"\n--- Point {index}/{len(points)}: density={point.get('density', 0)}, "
            f"dist={point_distance_from(point, drill_world):.1f}m, pos={format_point(target_world)} ---"
        )
        print(f"  GPS target: {gps_line('Nanobot target %03d %s' % (index, ore_subtype), target_world)}")

        if args.area_debug_points > 0 and index <= args.area_debug_points:
            debug_area_against_scan_points(
                points=points,
                center_world=target_world,
                left=left,
                up=up,
                fwd=fwd,
                area_size=args.area_size,
                max_rows=args.area_debug_rows,
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

            # If the helper telemetry says the area is centered on the target but
            # the real Nanobot reports no ore targets, the visible/working area is
            # probably using a different terminal-axis mapping than the helper
            # formula. Probe real Nanobot behavior by briefly trying candidate
            # axis/origin mappings and lock the one that actually exposes ore.
            if args.axis_probe_on_empty:
                visible_now, _current_now, _targets_now, ore_targets_now = ore_visible_now(drill, ore_subtype)
                if not visible_now and not ore_targets_now:
                    probe_candidate = probe_area_axis_candidates(
                        grid=grid,
                        drill=drill,
                        rc=rc,
                        ore_subtype=ore_subtype,
                        target_world=target_world,
                        area_size=args.area_size,
                        powered_seconds=args.axis_probe_powered_seconds,
                        max_candidates=args.axis_probe_max_candidates,
                        initial_label=axis_probe_locked_label,
                        target_dump=args.target_dump,
                    )
                    if probe_candidate is None:
                        if args.skip_empty_area_neighbors:
                            failed_clusters.append((target_world, empty_skip_radius))
                            print(
                                f"  Axis probe found no working mapping; registered this scan point as empty cluster center; "
                                f"nearby points within {empty_skip_radius:.1f}m will be skipped."
                            )
                        wait_idle(grid, drill, 2.5, "after-axis-probe-empty")
                        continue

                    probe_label, drill_world, left, up, fwd = probe_candidate
                    if args.axis_probe_lock:
                        axis_probe_locked_label = probe_label
                        print(f"  Locked real Nanobot AreaOffset frame for following points: {axis_probe_locked_label}")

                    # Count any raw ore collected during the powered probe.
                    _current_ore_probe, _ore_step_probe, mined_after_probe, _point_probe = ore_counter.update()
                    if mined_after_probe >= args.amount:
                        print(f"OK: target reached during axis probe, {ore_subtype} +{mined_after_probe:.1f}")
                        hard_stop(drill, hide_area=not args.keep_area)
                        return 0

            if not start_powered_collect(drill, drill_world, left, up, fwd, target_world, args.area_size):
                wait_idle(grid, drill, 3.0, "after-bad-start")
                continue

        ore_counter.start_point()
        point_baseline_stone = get_item_amount(grid, "Stone")

        result = mine_point(
            grid=grid,
            drill=drill,
            ore_subtype=ore_subtype,
            amount=args.amount,
            ore_counter=ore_counter,
            point_baseline_stone=point_baseline_stone,
            check_interval=args.check_interval,
            startup_timeout=args.startup_timeout,
            empty_powered_timeout=args.empty_powered_timeout,
            target_no_ore_timeout=args.target_no_ore_timeout,
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
            if args.skip_empty_area_neighbors:
                failed_clusters.append((target_world, empty_skip_radius))
                print(
                    f"  Empty/failed point registered as failed cluster center; "
                    f"nearby scan points within {empty_skip_radius:.1f}m will be skipped."
                )
            print("  Point failed or stayed empty; switching to the next selected scan point if any.")
            # In safe live-move mode result=1 can mean that a wrong Stone target
            # appeared and was stopped. Always wait until old targets settle
            # before moving the area again.
            wait_idle(grid, drill, 2.5 if args.live_move else 3.0, "after-point")
            continue
        if result == 2:
            print("ERROR: safety stop. The run was stopped to avoid cargo pollution.")
            return 4

    _current_ore, _ore_step, final_mined, _point_delta = ore_counter.update()
    print(f"ERROR: no dense {ore_subtype} point could be mined safely. Mined +{final_mined:.1f}/{args.amount:.1f}")
    hard_stop(drill, hide_area=True)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
