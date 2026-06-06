#!/usr/bin/env python3
"""
scan_probe_mine_ore_v6.py — полный комплекс:
  1. Сканирует руду OreDetectorDevice.scan_and_wait().
  2. Берёт точки выбранной руды из ore_cells().
  3. Сортирует точки по расстоянию от Nanobot Drill.
  4. Для каждой точки:
     - настраивает Nanobot в Collect;
     - включает только выбранную руду;
     - включает только класс Ore;
     - ставит AreaOffset точно на scan-точку;
     - ставит размер зоны;
     - кратко включает бур и проверяет, появилась ли нужная руда в targets/current/инвентаре.
  5. Если точка подходит — продолжает добычу до нужного delta amount.
  6. Если на точке идёт только Stone — быстро выключает бур и переходит к следующей точке.

Минимальный запуск:
  python examples/organized/drill_nano/scan_probe_mine_ore.py --grid skynet-baza1 --ore Platinum --amount 5000

Рекомендуемый запуск:
  python examples/organized/drill_nano/scan_probe_mine_ore.py --grid skynet-baza1 --ore Platinum --amount 5000 --scan-radius 500 --area-size 10

Важно:
  Для Nanobot на skynet-baza используется DRILL_AXIS_MAP как в set_nanodrill_area.py:
    LeftRight = grid Left
    UpDown    = grid Forward
    FrontBack = grid Up
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

# Совпадает с рабочим set_nanodrill_area.py для текущей установки Nanobot:
# Grid vector order: [Left/X, Up/Y, Forward/Z]
# Drill props:       [LeftRight, UpDown, FrontBack]
DRILL_AXIS_MAP = {
    "LeftRight": (0, 1),
    "UpDown": (2, 1),
    "FrontBack": (1, 1),
}

Vector = Tuple[float, float, float]


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(value or "").lower())


def format_point(point: Vector) -> str:
    return f"{point[0]:.3f} {point[1]:.3f} {point[2]:.3f}"


def vector_from_dict(data: Dict[str, Any]) -> Vector:
    return float(data["x"]), float(data["y"]), float(data["z"])


def point_from_any(value: Any) -> Optional[Vector]:
    if isinstance(value, dict):
        if {"x", "y", "z"}.issubset(value.keys()):
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


def get_item_amount(grid: Grid, item_subtype: str) -> float:
    total = 0.0
    wanted = item_subtype.lower()

    for item in grid.get_all_grid_items():
        subtype = str(item.get("item_subtype", ""))
        display = str(item.get("display_name", ""))
        if subtype.lower() == wanted or display.lower() == wanted:
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


def raw_filter_ok(drill: NanobotDrillSystemDevice, ore_subtype: str) -> bool:
    wanted = ore_subtype.strip().lower()

    ore_state: Dict[str, bool] = {}
    for entry in drill.debug_get_priority_list_raw():
        parsed = parse_priority_entry(entry)
        if parsed is None:
            continue
        ore_hash, enabled = parsed
        name = HASH_TO_ORE.get(ore_hash)
        if name:
            ore_state[name] = enabled

    resource_state: Dict[str, bool] = {}
    for entry in drill.debug_get_collect_priority_list_raw():
        parsed = parse_priority_entry(entry)
        if parsed is None:
            continue
        key, enabled = parsed
        name = RESOURCE_CLASS_NAMES.get(key)
        if name:
            resource_state[name.lower()] = enabled

    ore_ok = ore_state.get(wanted) is True and all(
        name == wanted or not enabled
        for name, enabled in ore_state.items()
    )

    resource_ok = resource_state.get("ore") is True and all(
        name == "ore" or not enabled
        for name, enabled in resource_state.items()
    )

    return ore_ok and resource_ok


def wait_for_filters(drill: NanobotDrillSystemDevice, ore_subtype: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout

    while time.time() < deadline:
        drill.wait_for_telemetry(timeout=2.0, wait_for_new=True, need_update=True)
        if raw_filter_ok(drill, ore_subtype):
            return True
        time.sleep(0.5)

    return False


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


def send_collect_filter_direct(drill: NanobotDrillSystemDevice, resources: List[str]) -> int:
    return drill.send_command(
        {
            "command": "CollectFilter",
            "payload": {
                "resources": list(resources),
            },
        }
    )


def send_ore_filter_direct(
    drill: NanobotDrillSystemDevice,
    ores: List[str],
    work_mode_value: int,
    apply_collect_filter: bool = True,
) -> int:
    return drill.send_command(
        {
            "command": "OreFilter",
            "payload": {
                "ores": list(ores),
                "workMode": int(work_mode_value),
                "applyCollectFilter": bool(apply_collect_filter),
            },
        }
    )


def force_work_mode(drill: NanobotDrillSystemDevice, mode_value: int, delay: float = 0.25) -> None:
    # Не используем drill.set_work_mode(): если wrapper старый, он снова перепутает Collect/Drill.
    safe_set_raw(drill, "Drill.WorkMode", int(mode_value))
    time.sleep(delay)


def get_drill_props(drill: NanobotDrillSystemDevice) -> Dict[str, Any]:
    drill.update()
    tel = drill.telemetry or {}
    props = tel.get("properties", {})
    return props if isinstance(props, dict) else {}


def is_on_value(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"true", "1", "on", "yes"}


def power_on_drill(
    drill: NanobotDrillSystemDevice,
    verify: bool = True,
    expected_work_mode: Optional[int] = None,
    retries: int = 3,
) -> bool:
    """
    Надёжное включение Nanobot.

    На этом блоке важно:
      - не использовать drill.set_work_mode(), если wrapper может быть старым;
      - выставлять Drill.WorkMode raw-значением ДО и ПОСЛЕ OnOff_On;
      - проверять телеметрию несколько раз, потому что она приходит с задержкой.
    """
    last_on = False

    for attempt in range(1, retries + 1):
        if expected_work_mode is not None:
            force_work_mode(drill, expected_work_mode, delay=0.2)

        try:
            drill.turn_on()
        except Exception as exc:
            print(f"WARNING: drill.turn_on() failed: {exc}")
            try:
                drill.run_action("OnOff_On")
            except Exception as action_exc:
                print(f"WARNING: OnOff_On action failed: {action_exc}")
                safe_set_raw(drill, "OnOff", True)

        time.sleep(0.8)

        if expected_work_mode is not None:
            force_work_mode(drill, expected_work_mode, delay=0.2)
            try:
                drill.run_action("OnOff_On")
            except Exception:
                pass
            time.sleep(0.8)

        if not verify:
            return True

        props = get_drill_props(drill)
        onoff = props.get("OnOff")
        enabled = props.get("Enabled")
        functional = props.get("IsFunctional")
        working = props.get("IsWorking")
        show_area = props.get("Drill.ShowArea")
        work_mode = props.get("Drill.WorkMode")
        script_controlled = props.get("Drill.ScriptControlled")

        last_on = True if onoff is None else is_on_value(onoff)

        print(
            f"  power check {attempt}/{retries}: "
            f"OnOff={onoff}, Enabled={enabled}, IsFunctional={functional}, "
            f"IsWorking={working}, ShowArea={show_area}, WorkMode={work_mode}, "
            f"ScriptControlled={script_controlled}"
        )

        mode_ok = True
        if expected_work_mode is not None and work_mode is not None:
            try:
                mode_ok = int(work_mode) == int(expected_work_mode)
            except (TypeError, ValueError):
                mode_ok = False

        if last_on and mode_ok:
            return True

    return last_on


def power_off_drill(drill: NanobotDrillSystemDevice, hide_area: bool = False) -> None:
    try:
        if hide_area:
            drill.turn_off()
        else:
            drill.run_action("OnOff_Off")
    except Exception as exc:
        print(f"WARNING: power off action failed: {exc}")
        safe_set_raw(drill, "OnOff", False)

    time.sleep(0.25)

    if hide_area:
        safe_set_raw(drill, "Drill.ShowArea", False)
        time.sleep(0.1)


def stop_drill(drill: NanobotDrillSystemDevice, hide_area: bool = False) -> None:
    power_off_drill(drill, hide_area=hide_area)


def configure_collect_mode(
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    use_conveyor: bool,
    filter_timeout: float = 20.0,
) -> bool:
    """
    Strict final Collect mode.

    Не используем:
      - drill.set_work_mode("Collect")
      - drill.set_ore_filters(..., work_mode="Collect")

    потому что в старом wrapper Collect/Drill перепутаны.
    Здесь все mode-значения отправляются напрямую:
      Drill=1, Collect=2, Fill=4.
    """
    wanted = ore_subtype.strip()
    if not wanted:
        return False

    for attempt in range(1, 6):
        print(f"  collect filter setup attempt {attempt}/5...")

        stop_drill(drill, hide_area=True)
        time.sleep(0.4)

        safe_action(drill, "CollectIfIdle_Off")
        safe_action(drill, "TerrainClearingMode_Off")
        safe_set_raw(drill, "Drill.CollectIfIdle", False)
        safe_set_raw(drill, "Drill.TerrainClearingMode", False)
        safe_set_raw(drill, "DrillSystem.CollectIfIdle", False)
        safe_set_raw(drill, "DrillSystem.TerrainClearingMode", False)

        safe_set_raw(drill, "UseConveyor", bool(use_conveyor))
        safe_set_raw(drill, "Drill.UseConveyor", bool(use_conveyor))
        safe_set_raw(drill, "DrillSystem.UseConveyor", bool(use_conveyor))

        safe_set_raw(drill, "Drill.ScriptControlled", True)
        time.sleep(0.5)

        try:
            drill.set_script_controlled(True)
            time.sleep(0.2)
        except Exception:
            pass

        send_collect_filter_direct(drill, ["Ore"])
        time.sleep(0.5)

        send_ore_filter_direct(
            drill,
            [wanted],
            work_mode_value=WORK_MODE_VALUES["Collect"],
            apply_collect_filter=True,
        )
        time.sleep(0.8)

        force_work_mode(drill, WORK_MODE_VALUES["Collect"], delay=0.4)

        safe_set_raw(drill, "Drill.ScriptControlled", False)
        time.sleep(0.5)

        try:
            drill.set_script_controlled_action(False)
            time.sleep(0.3)
        except Exception:
            pass

        force_work_mode(drill, WORK_MODE_VALUES["Collect"], delay=0.5)

        safe_action(drill, "CollectIfIdle_Off")
        safe_action(drill, "TerrainClearingMode_Off")
        safe_set_raw(drill, "Drill.CollectIfIdle", False)
        safe_set_raw(drill, "Drill.TerrainClearingMode", False)

        if wait_for_filters(drill, wanted, timeout=filter_timeout):
            print("  collect filters confirmed by RAW lists")
            return True

        print("  collect filters not confirmed yet; current RAW lists:")
        print_raw_filters(drill)

    return False


def configure_drill_probe_mode(
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    use_conveyor: bool,
) -> bool:
    """
    Probe/opening mode.

    Для поиска Platinum точек лучше использовать Drill mode:
      - разрешаем Stone + выбранную руду;
      - conveyor по умолчанию OFF;
      - как только Platinum появляется в PossibleDrillTargets, скрипт останавливает бур.

    Этот режим не предназначен для финальной добычи.
    """
    wanted = ore_subtype.strip()
    if not wanted:
        return False

    print("  configuring Drill probe/opening mode...")

    stop_drill(drill, hide_area=True)
    time.sleep(0.4)

    safe_action(drill, "CollectIfIdle_Off")
    safe_action(drill, "TerrainClearingMode_Off")
    safe_set_raw(drill, "Drill.CollectIfIdle", False)
    safe_set_raw(drill, "Drill.TerrainClearingMode", False)
    safe_set_raw(drill, "DrillSystem.CollectIfIdle", False)
    safe_set_raw(drill, "DrillSystem.TerrainClearingMode", False)

    safe_set_raw(drill, "UseConveyor", bool(use_conveyor))
    safe_set_raw(drill, "Drill.UseConveyor", bool(use_conveyor))
    safe_set_raw(drill, "DrillSystem.UseConveyor", bool(use_conveyor))

    safe_set_raw(drill, "Drill.ScriptControlled", True)
    time.sleep(0.4)

    try:
        send_collect_filter_direct(drill, ["none"])
        time.sleep(0.3)
    except Exception:
        pass

    send_ore_filter_direct(
        drill,
        ["Stone", wanted],
        work_mode_value=WORK_MODE_VALUES["Drill"],
        apply_collect_filter=False,
    )
    time.sleep(0.6)

    force_work_mode(drill, WORK_MODE_VALUES["Drill"], delay=0.4)

    safe_set_raw(drill, "Drill.ScriptControlled", False)
    time.sleep(0.4)

    try:
        drill.set_script_controlled_action(False)
        time.sleep(0.2)
    except Exception:
        pass

    force_work_mode(drill, WORK_MODE_VALUES["Drill"], delay=0.4)

    print("  Drill probe mode configured")
    print_raw_filters(drill)
    return True


def extract_ore_name(cell: Dict[str, Any]) -> str:
    for key in ("ore", "Ore", "material", "Material", "materialName", "MaterialName", "minedOre", "MinedOre"):
        value = cell.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if "/" in text:
                text = text.rsplit("/", 1)[-1]
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

    # Fallback: иногда координаты лежат плоско.
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


def point_distance_from(point: Dict[str, Any], origin: Vector) -> float:
    return v_len(v_sub(point["position"], origin))


def probe_point(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    drill_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    point: Dict[str, Any],
    area_size: float,
    point_timeout: float,
    check_interval: float,
    max_stone_delta_per_point: float,
    target_dump: int,
    point_index: int,
    total_points: int,
    probe_work_mode_value: int,
    accept_ore_delta_during_probe: bool,
) -> Tuple[bool, float, float]:
    target_world = point["position"]

    point_ore_baseline = get_ore_amount(grid, ore_subtype)
    point_stone_baseline = get_item_amount(grid, "Stone")

    stop_drill(drill, hide_area=False)

    drill_fb, drill_ud, drill_lr, distance_to_drill = set_area_to_world_target(
        drill,
        drill_world,
        left,
        up,
        fwd,
        target_world,
        area_size,
    )

    force_work_mode(drill, probe_work_mode_value, delay=0.2)
    safe_set_raw(drill, "Drill.ShowArea", True)
    time.sleep(0.2)
    power_on_drill(drill, expected_work_mode=probe_work_mode_value)

    print(
        f"[probe {point_index}/{total_points}] "
        f"target={format_point(target_world)} "
        f"dist={distance_to_drill:.1f}m content={point.get('content', 0):.1f} "
        f"area FB={drill_fb:+.1f} UD={drill_ud:+.1f} LR={drill_lr:+.1f}"
    )

    start = time.time()
    last_print = 0.0
    final_ore_delta = 0.0
    final_stone_delta = 0.0

    while time.time() - start < point_timeout:
        time.sleep(max(0.2, check_interval))

        current, targets, _props = read_targets(drill)
        ore_targets = [target for target in targets if target_has_ore(target, ore_subtype)]
        current_ok = current is not None and current_has_ore(current, targets, ore_subtype)

        final_ore_delta = get_ore_amount(grid, ore_subtype) - point_ore_baseline
        final_stone_delta = get_item_amount(grid, "Stone") - point_stone_baseline

        found_by_target = bool(ore_targets) or current_ok
        found_by_inventory = final_ore_delta > 0.01

        if found_by_target or (accept_ore_delta_during_probe and found_by_inventory):
            reason = "target/current" if found_by_target else "inventory delta"
            print(
                f"  FOUND by {reason}: targets={len(targets)}, {ore_subtype}={len(ore_targets)}, "
                f"{ore_subtype} +{final_ore_delta:.1f}, Stone +{final_stone_delta:.1f}, current={current}"
            )
            if targets:
                dump_targets(targets, ore_subtype, target_dump)
            return True, final_ore_delta, final_stone_delta

        if found_by_inventory:
            print(
                f"  NOTE: {ore_subtype} inventory grew by +{final_ore_delta:.1f}, "
                f"but PossibleDrillTargets still has {ore_subtype}=0. "
                "Not locking this point yet."
            )

        if max_stone_delta_per_point > 0 and final_stone_delta > max_stone_delta_per_point:
            print(
                f"  Stone +{final_stone_delta:.1f} > {max_stone_delta_per_point:.1f}; next point"
            )
            return False, final_ore_delta, final_stone_delta

        elapsed = time.time() - start
        if last_print == 0.0 or elapsed - last_print >= 5.0:
            last_print = elapsed
            print(
                f"  [{elapsed:.0f}/{point_timeout:.0f}s] "
                f"targets={len(targets)}, {ore_subtype}=0, "
                f"{ore_subtype} +{final_ore_delta:.1f}, Stone +{final_stone_delta:.1f}, current={current}"
            )

    return False, final_ore_delta, final_stone_delta


def mine_at_found_point(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    ore_subtype: str,
    amount: float,
    check_interval: float,
    stone_safety_delta: float,
    target_dump: int,
) -> int:
    baseline_ore = get_ore_amount(grid, ore_subtype)
    baseline_stone = get_item_amount(grid, "Stone")

    print()
    print(f"Mining {ore_subtype} until +{amount:.1f}")
    print(f"Mining baseline {ore_subtype}: {baseline_ore:.1f}")
    print(f"Mining baseline Stone: {baseline_stone:.1f}")
    print(f"Stone safety delta: {stone_safety_delta:.1f}")

    force_work_mode(drill, WORK_MODE_VALUES["Collect"], delay=0.3)
    started = power_on_drill(drill, expected_work_mode=WORK_MODE_VALUES["Collect"], retries=5)
    if not started:
        print("ERROR: final mining could not power on Nanobot in Collect mode")
        stop_drill(drill, hide_area=False)
        return 6

    start = time.time()

    while True:
        time.sleep(check_interval)

        current_amount = get_ore_amount(grid, ore_subtype)
        stone_amount = get_item_amount(grid, "Stone")

        mined = current_amount - baseline_ore
        stone_delta = stone_amount - baseline_stone
        elapsed = time.time() - start
        rate = mined / elapsed if elapsed > 0 else 0.0
        remaining = max(0.0, amount - mined)
        eta = remaining / rate if rate > 0 else float("inf")

        current, targets, _props = read_targets(drill)
        ore_targets = [target for target in targets if target_has_ore(target, ore_subtype)]
        current_ok = current is not None and current_has_ore(current, targets, ore_subtype)

        print(
            f"  [{elapsed:.0f}s] {ore_subtype}: +{mined:.1f}/{amount:.1f}, "
            f"Stone +{stone_delta:.1f}, targets={len(targets)}, {ore_subtype}={len(ore_targets)}, "
            f"rate={rate:.1f}/s, eta={eta:.0f}s, current={current}"
        )

        if mined >= amount:
            print(f"Target reached: +{mined:.1f} >= +{amount:.1f}")
            stop_drill(drill, hide_area=False)
            return 0

        if not current_ok and not ore_targets and mined <= 0.01:
            print()
            print("SAFETY STOP: requested ore disappeared before mining started.")
            if targets:
                dump_targets(targets, ore_subtype, target_dump)
            stop_drill(drill, hide_area=False)
            return 4

        if current is not None and not current_ok and mined > 0.01:
            print()
            print("SAFETY STOP: current target changed to non-requested material.")
            print(f"Current: {current}")
            if targets:
                dump_targets(targets, ore_subtype, target_dump)
            stop_drill(drill, hide_area=False)
            return 4

        if stone_safety_delta >= 0 and stone_delta > stone_safety_delta:
            print()
            print("SAFETY STOP: Stone increased during mining.")
            print(f"Stone delta: +{stone_delta:.1f}; limit: +{stone_safety_delta:.1f}")
            stop_drill(drill, hide_area=False)
            return 4



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
    )

    get_navigation_frame = _dynamic_get_navigation_frame
    set_area_to_world_target = _dynamic_set_area_to_world_target
    drill_offsets_from_local_vector = _dynamic_drill_offsets_from_local_vector
    get_block_local_position = _dynamic_get_block_local_position
    get_drill_local_offset = _dynamic_get_drill_local_offset
    try:
        grid_vector_from_drill_offsets = _dynamic_grid_vector_from_drill_offsets
    except NameError:
        pass
except Exception as _dynamic_area_import_error:
    print(f"WARNING: dynamic Nanobot area helper unavailable: {_dynamic_area_import_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ore, probe scan points by Nanobot, and mine target amount")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--ore", required=True, help="Ore type, e.g. Platinum")
    parser.add_argument("--amount", type=float, required=True, help="Target delta amount to mine")
    parser.add_argument("--scan-radius", type=float, default=500.0, help="Ore detector scan radius")
    parser.add_argument("--scan-timeout", type=float, default=45.0, help="Ore detector scan timeout")
    parser.add_argument("--area-size", type=float, default=10.0, help="Nanobot area width/height/depth")
    parser.add_argument("--point-timeout", type=float, default=8.0, help="How long to test each scan point")
    parser.add_argument("--check-interval", type=float, default=5.0, help="Mining monitor interval")
    parser.add_argument("--probe-check-interval", type=float, default=1.0, help="Probe monitor interval")
    parser.add_argument("--max-points", type=int, default=60, help="Maximum scan points to probe; 0 means all")
    parser.add_argument("--max-stone-delta-per-point", type=float, default=3000.0,
                        help="Move to next point if Stone grows by this much during probe; 0 disables")
    parser.add_argument("--stone-safety-delta", type=float, default=1000.0,
                        help="Stop mining if Stone grows by this much after ore point is found; -1 disables")
    parser.add_argument("--target-dump", type=int, default=20, help="How many targets to print for diagnostics")
    parser.add_argument("--use-conveyor-during-probe", action="store_true",
                        help="Enable conveyor during point probing. Default is off.")
    parser.add_argument("--strict-probe-filter", action="store_true",
                        help="Require strict ore-only filter during probing. Mostly useful with --probe-mode Collect.")
    parser.add_argument("--probe-mode", choices=["Drill", "Collect"], default="Drill",
                        help="How to probe scan points. Drill opens stone shell; Collect only checks already-visible ore.")
    parser.add_argument("--accept-ore-delta-during-probe", action="store_true",
                        help="Treat inventory ore growth during probe as a found point even if PossibleDrillTargets does not show the ore. Default: false.")
    args = parser.parse_args()

    ore_subtype = args.ore.strip()
    if not ore_subtype:
        print("ERROR: --ore must not be empty")
        return 1

    if ore_subtype.lower() not in ORE_HASHES:
        print(f"ERROR: unknown ore '{ore_subtype}'. Known ores: {', '.join(sorted(ORE_HASHES))}")
        return 1

    if args.amount <= 0:
        print("ERROR: --amount must be > 0")
        return 1

    if args.area_size <= 0:
        print("ERROR: --area-size must be > 0")
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

    print()
    print("=== STEP 1: Ore scan ===")
    points = scan_ore_points(grid, ore_subtype, radius=args.scan_radius, timeout=args.scan_timeout)
    if not points:
        print(f"ERROR: scan found no {ore_subtype} points")
        return 2

    print()
    print("=== STEP 2: Navigation frame ===")
    drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)

    points.sort(key=lambda point: point_distance_from(point, drill_world))
    if args.max_points > 0:
        points = points[:args.max_points]

    print(f"Points selected for probing: {len(points)}")
    for index, point in enumerate(points[:15], start=1):
        print(
            f"  #{index:02d}: dist={point_distance_from(point, drill_world):.1f}m "
            f"content={point.get('content', 0):.1f} pos={format_point(point['position'])}"
        )

    print()
    print("=== STEP 3: Configure probe mode ===")
    if args.probe_mode == "Drill":
        filter_ok = configure_drill_probe_mode(
            drill,
            ore_subtype=ore_subtype,
            use_conveyor=args.use_conveyor_during_probe,
        )
        probe_work_mode_value = WORK_MODE_VALUES["Drill"]
    else:
        filter_ok = configure_collect_mode(
            drill,
            ore_subtype=ore_subtype,
            use_conveyor=args.use_conveyor_during_probe,
        )
        probe_work_mode_value = WORK_MODE_VALUES["Collect"]

    if not filter_ok:
        print("WARNING: probe mode was not fully confirmed.")
        print("         Continuing may still work because the script checks PossibleDrillTargets directly.")
        print_raw_filters(drill)
        if args.strict_probe_filter:
            print("ERROR: --strict-probe-filter was requested")
            return 3

    global_baseline_ore = get_ore_amount(grid, ore_subtype)
    global_baseline_stone = get_item_amount(grid, "Stone")
    print()
    print(f"Global baseline {ore_subtype}: {global_baseline_ore:.1f}")
    print(f"Global baseline Stone: {global_baseline_stone:.1f}")

    print()
    print("=== STEP 4: Probe scan points ===")
    found_point: Optional[Dict[str, Any]] = None

    try:
        for index, point in enumerate(points, start=1):
            # ВАЖНО:
            # Nanobot иногда сбрасывает RAW filter lists в all=True сразу после включения/остановки.
            # Для этапа поиска это не критично: мы не доверяем фильтру, а смотрим напрямую
            # в PossibleDrillTargets и держим conveyor OFF по умолчанию.
            # Строгий фильтр обязателен только на финальном этапе добычи.
            if args.strict_probe_filter and args.probe_mode == "Collect" and not raw_filter_ok(drill, ore_subtype):
                print("Filters drifted, reconfiguring because --strict-probe-filter is set...")
                if not configure_collect_mode(
                    drill,
                    ore_subtype=ore_subtype,
                    use_conveyor=args.use_conveyor_during_probe,
                ):
                    print("ERROR: failed to reconfigure filters")
                    return 3

            found, ore_delta, stone_delta = probe_point(
                grid=grid,
                drill=drill,
                ore_subtype=ore_subtype,
                drill_world=drill_world,
                left=left,
                up=up,
                fwd=fwd,
                point=point,
                area_size=args.area_size,
                point_timeout=args.point_timeout,
                check_interval=args.probe_check_interval,
                max_stone_delta_per_point=args.max_stone_delta_per_point,
                target_dump=args.target_dump,
                point_index=index,
                total_points=len(points),
                probe_work_mode_value=probe_work_mode_value,
                accept_ore_delta_during_probe=args.accept_ore_delta_during_probe,
            )

            stop_drill(drill, hide_area=False)

            if found:
                found_point = point
                break

    finally:
        stop_drill(drill, hide_area=False)

    if found_point is None:
        print()
        print(f"ERROR: Nanobot did not see {ore_subtype} at any scanned point.")
        print("Try one of these:")
        print("  --area-size 12")
        print("  --area-size 15")
        print("  --point-timeout 3")
        print("  --max-stone-delta-per-point 1000")
        print("Drill is OFF.")
        return 5

    target_world = found_point["position"]
    print()
    print("=== STEP 5: Lock found point and mine ===")
    print(f"Found point: {format_point(target_world)}")

    # Для добычи включаем conveyor, иначе руда может остаться в буре.
    final_filter_ok = configure_collect_mode(drill, ore_subtype=ore_subtype, use_conveyor=True)
    if not final_filter_ok:
        print("WARNING: final filter setup failed on current device handle. Re-resolving grid/devices and retrying...")
        stop_drill(drill, hide_area=True)
        time.sleep(3.0)

        grid = Grid.from_name(args.grid)
        drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
        rc_devices = grid.find_devices_by_type(RemoteControlDevice)
        if not drills or not rc_devices:
            print("ERROR: failed to re-resolve drill/RC")
            return 3

        drill = drills[0]
        rc = rc_devices[0]
        drill_world, left, up, fwd = get_navigation_frame(grid, drill, rc)
        final_filter_ok = configure_collect_mode(drill, ore_subtype=ore_subtype, use_conveyor=True)

    if not final_filter_ok:
        print("ERROR: failed to configure final strict collect mode")
        print_raw_filters(drill)
        print()
        print("Manual recovery:")
        print(f"  python examples/organized/drill_nano/configure_platinum_only.py")
        print(
            f"  python examples/organized/drill_nano/mine_until.py "
            f"--grid {args.grid} --ore {ore_subtype} --target {format_point(target_world)} "
            f"--amount {args.amount:g} --area-size {args.area_size:g}"
        )
        return 3

    set_area_to_world_target(
        drill,
        drill_world=drill_world,
        left=left,
        up=up,
        fwd=fwd,
        target_world=target_world,
        area_size=args.area_size,
    )

    force_work_mode(drill, WORK_MODE_VALUES["Collect"], delay=0.3)
    safe_set_raw(drill, "Drill.ShowArea", True)
    time.sleep(0.3)

    result = mine_at_found_point(
        grid=grid,
        drill=drill,
        ore_subtype=ore_subtype,
        amount=args.amount,
        check_interval=args.check_interval,
        stone_safety_delta=args.stone_safety_delta,
        target_dump=args.target_dump,
    )

    final_ore = get_ore_amount(grid, ore_subtype)
    final_stone = get_item_amount(grid, "Stone")
    print()
    print("=== FINAL ===")
    print(f"{ore_subtype}: {final_ore:.1f} (global delta +{final_ore - global_baseline_ore:.1f})")
    print(f"Stone: {final_stone:.1f} (global delta +{final_stone - global_baseline_stone:.1f})")
    print(f"Used target: {format_point(target_world)}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
