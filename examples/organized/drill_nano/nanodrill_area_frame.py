#!/usr/bin/env python3
"""Nanobot Drill area coordinate helpers.

The important rule learned from live game tests is that the Nanobot Drill
terminal AreaOffset axes must be recovered from the live block transform and
validated against the mod-reported current area. A previous v20 patch inverted
LeftRight/X and pushed the visible cube into deep space. v22 keeps the
observed terminal behavior for X/LeftRight and fixes the remaining Z/FrontBack
sign: positive AreaOffsetLeftRight follows block/grid LEFT, while positive
AreaOffsetFrontBack follows block/grid BACKWARD for the visible Nanobot area.
The old plugin-reported area.center can be self-consistent while the visible
area is wrong, so it is no longer used for default auto-calibration.

Supported telemetry sources, in default priority order:
  1. Grid block telemetry: blocks[].world_pos and blocks[].orientation.
  2. Nanobot device telemetry: position, orientation, area.axis.

The grid telemetry is preferred because it is tied to the exact physical block
from the grid dump. Older Nanobot device telemetry could publish area.axis/center
computed by the plugin helper rather than by the real mod, which made
center_error look correct while the in-game area was still wrong.

Default axis mapping for `auto` is now the mod-observed safe mapping:

  AreaOffsetLeftRight  -> block/grid LEFT axis
  AreaOffsetUpDown      -> block/grid UP axis
  AreaOffsetFrontBack   -> block/grid BACKWARD axis

v21 also uses the current reported area.center only as a sanity check to infer
the terminal-axis sign from already-existing offsets. It no longer uses
area.center to invent a moving origin from RC metadata.

For diagnostics only, the source priority and mapping can be changed with:
  NANODRILL_TRANSFORM_PRIORITY=ship-local|device|grid
  NANODRILL_AREA_AXIS_MODE=auto|left-up-backward|left-up-forward|right-up-forward|right-up-backward
  NANODRILL_AREA_ORIGIN_SOURCE=device|block|rc-local|reported-center
  NANODRILL_TRUST_REPORTED_AREA_CENTER_ORIGIN=1       # diagnostic only
  NANODRILL_ENABLE_AREA_TELEMETRY_AUTOCALIBRATION=1   # diagnostic only; may follow stale plugin area.center
  NANODRILL_AREA_CLOSED_LOOP=1                        # optional diagnostic closed-loop
  NANODRILL_DISABLE_AREA_TELEMETRY_AUTOCALIBRATION=1  # disable v21 sign sanity check

Older plugin builds did not expose block orientation. Mining scripts must not
silently use a legacy fixed axis map in that case, because it can point the
collection area into empty space on ships where the Nanobot is mounted with a
different rotation. Legacy fallback is available only for manual diagnostics
with NANODRILL_ALLOW_LEGACY_AREA_MAP=1.
"""

from __future__ import annotations

import itertools
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

Vector = Tuple[float, float, float]

# Legacy fallback only. New code uses Nanobot telemetry orientation and ignores
# this map when `drill.telemetry["orientation"]` is available.
LEGACY_DRILL_AXIS_MAP: Dict[str, Tuple[int, int]] = {
    "LeftRight": (0, 1),
    "UpDown": (2, 1),
    "FrontBack": (1, 1),
}


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


def v_norm(a: Vector) -> Vector:
    length = v_len(a)
    if length <= 1e-9:
        raise ValueError(f"Cannot normalize zero vector: {a}")
    return a[0] / length, a[1] / length, a[2] / length


def v_neg(a: Vector) -> Vector:
    return -a[0], -a[1], -a[2]


def get_block_local_position(grid: Grid, device_id: int | str) -> Optional[Vector]:
    if not hasattr(grid, "blocks") or not grid.blocks:
        return None

    wanted_id = str(device_id)
    blocks = grid.blocks.values() if isinstance(grid.blocks, dict) else grid.blocks
    for block in blocks:
        if str(getattr(block, "block_id", "")) != wanted_id:
            continue
        local_position = getattr(block, "local_position", None)
        point = point_from_any(local_position)
        if point is not None:
            return point

    return None


def get_block_info(grid: Grid, device_id: int | str) -> Optional[Any]:
    """Return BlockInfo/raw block payload for a device id from Grid.blocks."""
    if not hasattr(grid, "blocks") or not grid.blocks:
        return None

    wanted_id = str(device_id)
    blocks = grid.blocks.values() if isinstance(grid.blocks, dict) else grid.blocks
    for block in blocks:
        if isinstance(block, dict):
            raw_id = block.get("id") or block.get("blockId") or block.get("entityId")
            if str(raw_id) == wanted_id:
                return block
            continue

        if str(getattr(block, "block_id", "")) == wanted_id:
            return block

    return None


def get_block_extra_value(block: Any, *keys: str) -> Any:
    """Read a value from BlockInfo.extra or from a raw block dict."""
    if block is None:
        return None

    if isinstance(block, dict):
        for key in keys:
            if key in block:
                return block.get(key)
        return None

    extra = getattr(block, "extra", None)
    if isinstance(extra, dict):
        for key in keys:
            if key in extra:
                return extra.get(key)

    for key in keys:
        attr_name = key
        if hasattr(block, attr_name):
            return getattr(block, attr_name)

    return None


def get_block_world_position(block: Any) -> Optional[Vector]:
    for key in ("world_pos", "worldPos", "worldPosition", "position", "Position"):
        point = point_from_any(get_block_extra_value(block, key))
        if point is not None:
            return point

    # Last-resort approximation for older grid telemetry. This is only used as
    # a position fallback; orientation must still come from real orientation
    # telemetry, not from bounding_box.
    bounding_box = getattr(block, "bounding_box", None) if block is not None else None
    if bounding_box is None and isinstance(block, dict):
        bounding_box = block.get("bounding_box") or block.get("boundingBox")
    if isinstance(bounding_box, dict):
        bb_min = point_from_any(bounding_box.get("min") or bounding_box.get("Min"))
        bb_max = point_from_any(bounding_box.get("max") or bounding_box.get("Max"))
        if bb_min is not None and bb_max is not None:
            return (
                (bb_min[0] + bb_max[0]) * 0.5,
                (bb_min[1] + bb_max[1]) * 0.5,
                (bb_min[2] + bb_max[2]) * 0.5,
            )

    return None


def get_block_orientation(block: Any) -> Dict[str, Any]:
    orientation = get_block_extra_value(block, "orientation", "Orientation")
    return orientation if isinstance(orientation, dict) else {}


def get_block_local_orientation(block: Any) -> Dict[str, Any]:
    orientation = get_block_extra_value(block, "local_orientation", "localOrientation", "LocalOrientation")
    return orientation if isinstance(orientation, dict) else {}




def _first_number(value: Any, *keys: str) -> Optional[float]:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                try:
                    return float(value.get(key))
                except (TypeError, ValueError):
                    pass
    return None


def _area_dict_from_telemetry(drill: NanobotDrillSystemDevice) -> Dict[str, Any]:
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
    return area if isinstance(area, dict) else {}


def _area_offsets_from_telemetry(drill: NanobotDrillSystemDevice, area: Optional[Dict[str, Any]] = None) -> Optional[Tuple[float, float, float]]:
    """Return terminal offsets as (front_back, up_down, left_right)."""
    if area is None:
        area = _area_dict_from_telemetry(drill)

    fb = _first_number(area, "offsetFrontBack", "frontBack", "FrontBack", "areaOffsetFrontBack")
    ud = _first_number(area, "offsetUpDown", "upDown", "UpDown", "areaOffsetUpDown")
    lr = _first_number(area, "offsetLeftRight", "leftRight", "LeftRight", "areaOffsetLeftRight")

    if fb is not None and ud is not None and lr is not None:
        return fb, ud, lr

    telemetry = drill.telemetry or {}
    props = telemetry.get("properties", {}) if isinstance(telemetry.get("properties"), dict) else {}
    fb = _first_number(props, "Drill.AreaOffsetFrontBack", "AreaOffsetFrontBack")
    ud = _first_number(props, "Drill.AreaOffsetUpDown", "AreaOffsetUpDown")
    lr = _first_number(props, "Drill.AreaOffsetLeftRight", "AreaOffsetLeftRight")
    if fb is not None and ud is not None and lr is not None:
        return fb, ud, lr

    return None


def _area_sizes_from_telemetry(drill: NanobotDrillSystemDevice, area: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[float]]:
    if area is None:
        area = _area_dict_from_telemetry(drill)
    telemetry = drill.telemetry or {}
    props = telemetry.get("properties", {}) if isinstance(telemetry.get("properties"), dict) else {}
    return {
        "width": _first_number(area, "width", "Width", "areaWidth") or _first_number(props, "Drill.AreaWidth", "AreaWidth"),
        "height": _first_number(area, "height", "Height", "areaHeight") or _first_number(props, "Drill.AreaHeight", "AreaHeight"),
        "depth": _first_number(area, "depth", "Depth", "areaDepth") or _first_number(props, "Drill.AreaDepth", "AreaDepth"),
    }


def _origin_from_reported_area_center(
    drill: NanobotDrillSystemDevice,
    left_right_axis: Vector,
    up_down_axis: Vector,
    front_back_axis: Vector,
) -> Tuple[Optional[Vector], str]:
    """Recover the mod's internal AreaOffset origin from reported area center.

    Grid block `world_pos` is the physical block center, but the Nanobot mod may
    use another internal origin for AreaOffset. If the plugin exposes current
    area.center and current offsets, the safest origin is:

        origin = center - LR*AreaOffsetLeftRight - UD*AreaOffsetUpDown - FB*AreaOffsetFrontBack

    This removes the persistent 1-small-block / 2.5m offset seen between
    blocks[].world_pos and Nanobot device area center.
    """
    area = _area_dict_from_telemetry(drill)
    center = point_from_any(area.get("center") or area.get("Center"))
    offsets = _area_offsets_from_telemetry(drill, area)
    if center is None or offsets is None:
        return None, ""

    front_back, up_down, left_right = offsets
    origin = v_sub(
        center,
        v_add(
            v_mul(left_right_axis, left_right),
            v_add(v_mul(up_down_axis, up_down), v_mul(front_back_axis, front_back)),
        ),
    )
    return origin, (
        "reported Nanobot area.center minus current AreaOffset "
        f"(FB={front_back:+.2f}, UD={up_down:+.2f}, LR={left_right:+.2f})"
    )


def _format_vec(value: Optional[Vector]) -> str:
    if value is None:
        return "None"
    return f"({value[0]:+.3f}, {value[1]:+.3f}, {value[2]:+.3f})"


def _vector_dict(value: Vector) -> Dict[str, float]:
    return {"x": float(value[0]), "y": float(value[1]), "z": float(value[2])}


def _orientation_dict_from_axes(left_axis: Vector, up_axis: Vector, forward_axis: Vector) -> Dict[str, Dict[str, float]]:
    """Build an orientation dict compatible with _candidate_area_axis_mappings()."""
    return {
        "left": _vector_dict(left_axis),
        "right": _vector_dict(v_neg(left_axis)),
        "up": _vector_dict(up_axis),
        "down": _vector_dict(v_neg(up_axis)),
        "forward": _vector_dict(forward_axis),
        "backward": _vector_dict(v_neg(forward_axis)),
    }


def _print_axis_diagnostics(left_right_axis: Vector, up_down_axis: Vector, front_back_axis: Vector) -> None:
    lr_len = v_len(left_right_axis)
    ud_len = v_len(up_down_axis)
    fb_len = v_len(front_back_axis)
    lr_ud = v_dot(left_right_axis, up_down_axis)
    lr_fb = v_dot(left_right_axis, front_back_axis)
    ud_fb = v_dot(up_down_axis, front_back_axis)
    handed = v_dot(v_cross(left_right_axis, up_down_axis), front_back_axis)
    print(
        "  Axis diagnostics: "
        f"len(LR)={lr_len:.4f}, len(UD)={ud_len:.4f}, len(FB)={fb_len:.4f}, "
        f"dot(LR,UD)={lr_ud:+.4f}, dot(LR,FB)={lr_fb:+.4f}, dot(UD,FB)={ud_fb:+.4f}, "
        f"handedness={handed:+.4f}"
    )


def get_grid_left_axis(orientation: Dict[str, Any]) -> Vector:
    left = orientation.get("left") or orientation.get("Left")
    if left:
        return v_norm(vector_from_dict(left))

    right = orientation.get("right") or orientation.get("Right")
    if right:
        return v_neg(v_norm(vector_from_dict(right)))

    forward = v_norm(vector_from_dict(orientation["forward"]))
    up = v_norm(vector_from_dict(orientation["up"]))
    return v_neg(v_norm(v_cross(forward, up)))


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


def _read_rc_frame(rc: RemoteControlDevice) -> Tuple[Vector, Vector, Vector, Vector]:
    # Compatibility fallback for callers that do not pass Grid. New mining code
    # uses _read_true_grid_frame_from_rc(grid, rc) so RC local_orientation is honored.
    rc.update()
    time.sleep(0.15)
    rc.update()

    telemetry = rc.telemetry or {}
    rc_pos_raw = telemetry.get("position", {})
    orientation = telemetry.get("orientation", {})
    if not rc_pos_raw or not orientation:
        raise RuntimeError("No Remote Control position/orientation telemetry")

    rc_pos = vector_from_dict(rc_pos_raw)
    grid_forward = v_norm(vector_from_dict(orientation["forward"]))
    grid_up = v_norm(vector_from_dict(orientation["up"]))
    grid_left = get_grid_left_axis(orientation)
    return rc_pos, grid_left, grid_up, grid_forward


def _world_from_rc_local(
    rc_pos: Vector,
    grid_left: Vector,
    grid_up: Vector,
    grid_forward: Vector,
    local: Vector,
) -> Vector:
    return v_add(
        rc_pos,
        v_add(
            v_mul(grid_left, local[0]),
            v_add(v_mul(grid_up, local[1]), v_mul(grid_forward, local[2])),
        ),
    )



_DIRECTION_ALIASES = {
    "forward": "forward",
    "forwards": "forward",
    "backward": "backward",
    "backwards": "backward",
    "back": "backward",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
}

_OPPOSITE_DIRECTION = {
    "forward": "backward",
    "backward": "forward",
    "up": "down",
    "down": "up",
    "left": "right",
    "right": "left",
}


def _direction_name(value: Any) -> Optional[str]:
    text = str(value or "").strip().replace(" ", "").replace("_", "").replace("-", "").lower()
    return _DIRECTION_ALIASES.get(text)


def _opposite_direction_name(name: str) -> str:
    return _OPPOSITE_DIRECTION[name]


def _axis_world_by_grid_direction(grid_left: Vector, grid_up: Vector, grid_forward: Vector) -> Dict[str, Vector]:
    return {
        "left": grid_left,
        "right": v_neg(grid_left),
        "up": grid_up,
        "down": v_neg(grid_up),
        "forward": grid_forward,
        "backward": v_neg(grid_forward),
    }


def _derive_grid_axes_from_block_world_orientation(
    block_orientation: Dict[str, Any],
    block_local_orientation: Dict[str, Any],
) -> Optional[Tuple[Vector, Vector, Vector, str]]:
    """Recover grid left/up/forward world axes from one block orientation.

    Device telemetry gives a block's own world Forward/Up/Left. Metadata
    local_orientation tells which grid direction that block Forward/Up point to.
    Combining them lets us recover the true ship-grid axes even if the RC is
    mounted sideways.

    Space Engineers block frames are treated as left-handed names with the
    relation: Left x Up = Forward. Therefore:
      Left    = Up x Forward
      Up      = Forward x Left
      Forward = Left x Up
    """
    if not isinstance(block_orientation, dict) or not isinstance(block_local_orientation, dict):
        return None

    local_forward = _direction_name(block_local_orientation.get("forward") or block_local_orientation.get("Forward"))
    local_up = _direction_name(block_local_orientation.get("up") or block_local_orientation.get("Up"))
    if local_forward is None or local_up is None:
        return None

    block_forward = _axis_by_name(block_orientation, "forward")
    block_up = _axis_by_name(block_orientation, "up")
    if block_forward is None or block_up is None:
        return None

    grid_left: Optional[Vector] = None
    grid_up: Optional[Vector] = None
    grid_forward: Optional[Vector] = None

    def assign_grid_direction(direction: str, axis: Vector) -> None:
        nonlocal grid_left, grid_up, grid_forward
        if direction == "left":
            grid_left = axis
        elif direction == "right":
            grid_left = v_neg(axis)
        elif direction == "up":
            grid_up = axis
        elif direction == "down":
            grid_up = v_neg(axis)
        elif direction == "forward":
            grid_forward = axis
        elif direction == "backward":
            grid_forward = v_neg(axis)

    assign_grid_direction(local_forward, block_forward)
    assign_grid_direction(local_up, block_up)

    # Infer the missing grid axis using Left x Up = Forward.
    if grid_left is None and grid_up is not None and grid_forward is not None:
        grid_left = v_norm(v_cross(grid_up, grid_forward))
    if grid_up is None and grid_forward is not None and grid_left is not None:
        grid_up = v_norm(v_cross(grid_forward, grid_left))
    if grid_forward is None and grid_left is not None and grid_up is not None:
        grid_forward = v_norm(v_cross(grid_left, grid_up))

    if grid_left is None or grid_up is None or grid_forward is None:
        return None

    # Normalize and re-orthogonalize to avoid drift.
    grid_left = v_norm(grid_left)
    grid_up = v_norm(grid_up)
    grid_forward = v_norm(grid_forward)
    grid_forward = v_norm(v_cross(grid_left, grid_up))
    grid_left = v_norm(v_cross(grid_up, grid_forward))
    grid_up = v_norm(v_cross(grid_forward, grid_left))

    source = f"grid axes recovered from block local_orientation={block_local_orientation}"
    return grid_left, grid_up, grid_forward, source

def _read_true_grid_frame_from_rc(
    grid: Grid,
    rc: RemoteControlDevice,
) -> Tuple[Vector, Vector, Vector, Vector, str]:
    """Read RC position and true ship-grid axes.

    Old code assumed RC world orientation == ship grid orientation. That is only
    true if the Remote Control block is mounted aligned to the grid. This helper
    uses RC local_orientation when available, so rotating the ship away from the
    ore does not corrupt the grid-local calculation.
    """
    rc.update()
    time.sleep(0.15)
    rc.update()

    telemetry = rc.telemetry or {}
    rc_pos_raw = telemetry.get("position", {})
    rc_orientation = telemetry.get("orientation", {})
    if not rc_pos_raw or not rc_orientation:
        raise RuntimeError("No Remote Control position/orientation telemetry")

    rc_pos = vector_from_dict(rc_pos_raw)
    rc_block = get_block_info(grid, rc.device_id)
    rc_local_orientation = get_block_local_orientation(rc_block) if rc_block is not None else {}

    recovered = _derive_grid_axes_from_block_world_orientation(rc_orientation, rc_local_orientation)
    if recovered is not None:
        grid_left, grid_up, grid_forward, source = recovered
        return rc_pos, grid_left, grid_up, grid_forward, "RC " + source

    # Fallback for old metadata: behaves like previous versions.
    grid_forward = v_norm(vector_from_dict(rc_orientation["forward"]))
    grid_up = v_norm(vector_from_dict(rc_orientation["up"]))
    grid_left = get_grid_left_axis(rc_orientation)
    return rc_pos, grid_left, grid_up, grid_forward, "RC orientation used as grid axes fallback"


def _block_axes_from_grid_and_local_orientation(
    grid_left: Vector,
    grid_up: Vector,
    grid_forward: Vector,
    local_orientation: Dict[str, Any],
) -> Optional[Tuple[Vector, Vector, Vector, str]]:
    """Return block Left/Up/Forward world axes from ship-grid axes + local_orientation."""
    if not isinstance(local_orientation, dict) or not local_orientation:
        return None

    local_forward = _direction_name(local_orientation.get("forward") or local_orientation.get("Forward"))
    local_up = _direction_name(local_orientation.get("up") or local_orientation.get("Up"))
    if local_forward is None or local_up is None:
        return None

    grid_axis = _axis_world_by_grid_direction(grid_left, grid_up, grid_forward)
    block_forward = grid_axis[local_forward]
    block_up = grid_axis[local_up]
    block_left = v_norm(v_cross(block_up, block_forward))

    # v22: X/LR positive follows block LEFT, and Z/FB positive follows block
    # BACKWARD. Previous builds used Forward for FB; the visible miss then
    # became approximately 2*|FB|, e.g. FB=-194 produced a ~388m visual shift.
    mode = _normalize_axis_mode()
    effective_mode = "left-up-backward" if mode == "auto" else mode
    axis_by_name = {
        "left": block_left,
        "right": v_neg(block_left),
        "up": block_up,
        "down": v_neg(block_up),
        "forward": block_forward,
        "backward": v_neg(block_forward),
    }
    parts = effective_mode.split("-")
    if len(parts) != 3 or any(part not in axis_by_name for part in parts):
        return None
    lr_axis = axis_by_name[parts[0]]
    ud_axis = axis_by_name[parts[1]]
    fb_axis = axis_by_name[parts[2]]
    return (
        lr_axis,
        ud_axis,
        fb_axis,
        f"Nanobot REAL terminal axes from ship grid + block local_orientation={local_orientation} axis_mode={mode} effective={effective_mode}",
    )

def _pick_axis(orientation: Dict[str, Any], positive_name: str, negative_name: str) -> Optional[Vector]:
    positive = orientation.get(positive_name) or orientation.get(positive_name.capitalize())
    if positive:
        return v_norm(vector_from_dict(positive))

    negative = orientation.get(negative_name) or orientation.get(negative_name.capitalize())
    if negative:
        return v_neg(v_norm(vector_from_dict(negative)))

    return None


def _normalize_axis_mode(mode: Optional[str] = None) -> str:
    raw = str(mode if mode is not None else os.getenv("NANODRILL_AREA_AXIS_MODE", "auto")).strip().lower()
    aliases = {
        "": "auto",
        "default": "auto",
        "auto-calibrate": "auto",
        "calibrate": "auto",
        "right": "right-up-backward",
        "left": "left-up-backward",
        "ruf": "right-up-forward",
        "luf": "left-up-forward",
        "rub": "right-up-backward",
        "lub": "left-up-backward",
    }
    return aliases.get(raw, raw)


def _axis_by_name(orientation: Dict[str, Any], name: str) -> Optional[Vector]:
    name = name.strip().lower()
    if name == "right":
        return _pick_axis(orientation, "right", "left")
    if name == "left":
        return _pick_axis(orientation, "left", "right")
    if name == "up":
        return _pick_axis(orientation, "up", "down")
    if name == "down":
        return _pick_axis(orientation, "down", "up")
    if name == "forward":
        return _pick_axis(orientation, "forward", "backward")
    if name == "backward":
        return _pick_axis(orientation, "backward", "forward")
    return None


def _axes_for_named_mode(
    orientation: Dict[str, Any],
    mode: str,
) -> Tuple[Optional[Vector], Optional[Vector], Optional[Vector]]:
    """Return axes for explicit modes like left-up-forward."""
    if not isinstance(orientation, dict) or not orientation:
        return None, None, None

    mode = _normalize_axis_mode(mode)
    if mode == "auto":
        # v22: live screenshots show the remaining miss scales as 2*|FrontBack|.
        # That is a mirrored Z/FrontBack sign. The visible Nanobot cube uses
        # BACKWARD for positive FrontBack, while X/LeftRight uses LEFT.
        # Do not let old plugin area.center telemetry override this by default.
        mode = "left-up-backward"

    parts = mode.split("-")
    if len(parts) != 3:
        return None, None, None

    lr_name, ud_name, fb_name = parts
    left_right_axis = _axis_by_name(orientation, lr_name)
    up_down_axis = _axis_by_name(orientation, ud_name)
    front_back_axis = _axis_by_name(orientation, fb_name)

    if left_right_axis is None or up_down_axis is None or front_back_axis is None:
        return None, None, None
    return left_right_axis, up_down_axis, front_back_axis


def _candidate_area_axis_mappings(
    orientation: Dict[str, Any],
) -> List[Tuple[str, Vector, Vector, Vector]]:
    """Generate all possible terminal-property axis mappings.

    The normal expectation is LR=left/right, UD=up/down, FB=forward/backward.
    But for debugging we also test permutations because the user can visually see
    when a terminal property is mapped to another block axis.
    """
    base_groups = {
        "lr": ("right", "left"),
        "ud": ("up", "down"),
        "fb": ("forward", "backward"),
    }

    # Physical base axis groups. We permute them across terminal properties and
    # then choose a sign/name inside each group.
    groups = ["lr", "ud", "fb"]
    group_to_names = {
        "lr": base_groups["lr"],
        "ud": base_groups["ud"],
        "fb": base_groups["fb"],
    }

    result: List[Tuple[str, Vector, Vector, Vector]] = []
    seen = set()
    for assigned_groups in itertools.permutations(groups, 3):
        for signs in itertools.product((0, 1), repeat=3):
            lr_name = group_to_names[assigned_groups[0]][signs[0]]
            ud_name = group_to_names[assigned_groups[1]][signs[1]]
            fb_name = group_to_names[assigned_groups[2]][signs[2]]

            # Skip physically duplicated axis selections, e.g. LR=right and
            # UD=left are the same base axis and cannot form a 3D frame.
            base_set = {assigned_groups[0], assigned_groups[1], assigned_groups[2]}
            if len(base_set) != 3:
                continue

            lr = _axis_by_name(orientation, lr_name)
            ud = _axis_by_name(orientation, ud_name)
            fb = _axis_by_name(orientation, fb_name)
            if lr is None or ud is None or fb is None:
                continue

            label = f"LR={lr_name},UD={ud_name},FB={fb_name}"
            key = (
                round(lr[0], 6), round(lr[1], 6), round(lr[2], 6),
                round(ud[0], 6), round(ud[1], 6), round(ud[2], 6),
                round(fb[0], 6), round(fb[1], 6), round(fb[2], 6),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append((label, lr, ud, fb))
    return result


def _calibrate_axes_from_current_area(
    drill: NanobotDrillSystemDevice,
    orientation: Dict[str, Any],
    origin: Optional[Vector],
) -> Optional[Tuple[Vector, Vector, Vector, str]]:
    """Infer the real terminal slider axes from current area telemetry.

    If current offsets are non-zero, the reported area.center tells us which
    world direction every terminal offset really uses. We try all permutations
    and signs and choose the one that reproduces the current center.
    """
    if origin is None or not isinstance(orientation, dict) or not orientation:
        return None

    area = _area_dict_from_telemetry(drill)
    center = point_from_any(area.get("center") or area.get("Center"))
    offsets = _area_offsets_from_telemetry(drill, area)
    if center is None or offsets is None:
        return None

    front_back, up_down, left_right = offsets
    offset_norm = math.sqrt(front_back * front_back + up_down * up_down + left_right * left_right)
    if offset_norm < 1.0:
        print("  Auto axis calibration skipped: current AreaOffset is too small to infer axes")
        return None

    scored: List[Tuple[float, str, Vector, Vector, Vector, Vector]] = []
    for label, lr_axis, ud_axis, fb_axis in _candidate_area_axis_mappings(orientation):
        predicted = v_add(
            origin,
            v_add(
                v_mul(lr_axis, left_right),
                v_add(v_mul(ud_axis, up_down), v_mul(fb_axis, front_back)),
            ),
        )
        error = v_len(v_sub(predicted, center))
        scored.append((error, label, lr_axis, ud_axis, fb_axis, predicted))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0])
    print("  Auto axis calibration from current Nanobot area telemetry:")
    print(f"    origin={_format_vec(origin)}")
    print(f"    reported center={_format_vec(center)}")
    print(f"    current offsets: FB={front_back:+.2f}, UD={up_down:+.2f}, LR={left_right:+.2f}")
    for rank, (error, label, _lr, _ud, _fb, predicted) in enumerate(scored[:6], start=1):
        print(f"    #{rank}: error={error:.3f}m {label} predicted={_format_vec(predicted)}")

    best_error, best_label, best_lr, best_ud, best_fb, _best_predicted = scored[0]
    second_error = scored[1][0] if len(scored) > 1 else float("inf")
    if best_error > 5.0:
        print(
            "  WARNING: best auto axis calibration error is still high: "
            f"{best_error:.3f}m. Current area.center may be stale or origin may be wrong. "
            "Keeping the default v21 axis mapping."
        )
        return None
    if second_error < best_error + 0.5:
        print(
            "  WARNING: auto axis calibration is ambiguous: "
            f"best={best_error:.3f}m, second={second_error:.3f}m. "
            "Keeping the default v21 axis mapping."
        )
        return None

    return best_lr, best_ud, best_fb, f"auto-calibrated from current area telemetry ({best_label}, error={best_error:.3f}m)"


def _axes_from_orientation(
    orientation: Dict[str, Any],
) -> Tuple[Optional[Vector], Optional[Vector], Optional[Vector]]:
    """Convert block orientation to positive AreaOffset axes.

    `auto` falls back to left-up-backward. Current area.center from older
    DedicatedPlugin builds is diagnostic only because it can use the wrong
    FrontBack sign while the visible cube is elsewhere.
    """
    mode = _normalize_axis_mode()
    if mode not in {"auto", "right-up-forward", "left-up-forward", "right-up-backward", "left-up-backward"}:
        raise RuntimeError(
            "Unsupported NANODRILL_AREA_AXIS_MODE=%r. Use one of: "
            "auto, right-up-forward, left-up-forward, right-up-backward, left-up-backward." % mode
        )
    return _axes_for_named_mode(orientation, mode)


def _read_drill_transform_from_device(
    drill: NanobotDrillSystemDevice,
) -> Tuple[Optional[Vector], Optional[Vector], Optional[Vector], Optional[Vector], str]:
    """Return Nanobot world position and AreaOffset axes from device telemetry."""
    try:
        drill.wait_for_telemetry(timeout=2.0, wait_for_new=True, need_update=True)
    except Exception:
        try:
            drill.update()
            time.sleep(0.25)
        except Exception:
            pass

    telemetry = drill.telemetry or {}
    position = point_from_any(telemetry.get("position"))

    # Prefer the raw block orientation over area.axis. Older plugin builds
    # published area.axis.leftRight as WorldMatrix.Left, while the real Nanobot
    # AreaOffsetLeftRight slider moves along WorldMatrix.Right. Using orientation
    # avoids carrying that old sign bug forward.
    orientation = telemetry.get("orientation", {})
    left_right_axis, up_down_axis, front_back_axis = _axes_from_orientation(orientation)
    if left_right_axis is not None and up_down_axis is not None and front_back_axis is not None:
        mode = _normalize_axis_mode()
        return position, left_right_axis, up_down_axis, front_back_axis, "Nanobot device telemetry orientation axis_mode=" + mode

    # Last diagnostic fallback: accept area.axis only when explicitly requested.
    area = telemetry.get("area") if isinstance(telemetry.get("area"), dict) else {}
    axis = area.get("axis") if isinstance(area.get("axis"), dict) else {}
    if str(os.getenv("NANODRILL_ALLOW_DEVICE_AREA_AXIS", "")).strip().lower() in {"1", "true", "yes", "on"} and axis:
        left_right_raw = axis.get("leftRight") or axis.get("LeftRight")
        up_down_raw = axis.get("upDown") or axis.get("UpDown")
        front_back_raw = axis.get("frontBack") or axis.get("FrontBack")
        if left_right_raw and up_down_raw and front_back_raw:
            return (
                position,
                v_norm(vector_from_dict(left_right_raw)),
                v_norm(vector_from_dict(up_down_raw)),
                v_norm(vector_from_dict(front_back_raw)),
                "Nanobot device telemetry area.axis explicit diagnostic fallback",
            )

    return position, None, None, None, ""


def _read_drill_transform_from_grid_block(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
) -> Tuple[Optional[Vector], Optional[Vector], Optional[Vector], Optional[Vector], str]:
    """Return Nanobot transform from grid.blocks[] telemetry.

    This supports the newer grid telemetry where each block contains:
      - world_pos: exact block world position;
      - orientation: world vectors forward/backward/up/down/left/right;
      - local_orientation: block orientation relative to the grid, useful for logs.
    """
    block = get_block_info(grid, drill.device_id)
    if block is None:
        return None, None, None, None, ""

    position = get_block_world_position(block)
    orientation = get_block_orientation(block)
    left_right_axis, up_down_axis, front_back_axis = _axes_from_orientation(orientation)
    if left_right_axis is None or up_down_axis is None or front_back_axis is None:
        return position, None, None, None, ""

    local_orientation = get_block_local_orientation(block)
    source = "grid block orientation"
    if local_orientation:
        source += f" local_orientation={local_orientation}"
    source += " axis_mode=" + _normalize_axis_mode()

    return position, left_right_axis, up_down_axis, front_back_axis, source


def _read_drill_transform(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
) -> Tuple[Optional[Vector], Optional[Vector], Optional[Vector], Optional[Vector], str]:
    """Return Nanobot world position and AreaOffset axes.

    Default priority:
      1. LIVE Nanobot device telemetry position + orientation.
      2. Grid block telemetry blocks[].world_pos + blocks[].orientation.

    Reason: the visible Nanobot area is controlled by the live terminal block.
    Grid block dumps can be cached/stale after ship rotation, so device
    telemetry is authoritative for the AreaOffset frame. Grid telemetry is kept
    only as a comparison/fallback source.

    The returned axes are in AreaOffset property order:
      - left_right_axis: positive AreaOffsetLeftRight direction;
      - up_down_axis: positive AreaOffsetUpDown direction;
      - front_back_axis: positive AreaOffsetFrontBack direction.
    """
    block_pos, block_lr, block_ud, block_fb, block_source = _read_drill_transform_from_grid_block(grid, drill)
    device_pos, device_lr, device_ud, device_fb, device_source = _read_drill_transform_from_device(drill)

    priority = str(os.getenv("NANODRILL_TRANSFORM_PRIORITY", "device")).strip().lower()
    if priority not in {"ship-local", "device", "grid"}:
        raise RuntimeError("Unsupported NANODRILL_TRANSFORM_PRIORITY=%r. Use ship-local, device, or grid." % priority)

    # ship-local is handled in get_navigation_frame(), because it needs RC world
    # position plus block local offsets. Here we leave device/grid fallback intact.
    if priority == "ship-local":
        priority = "device"

    def maybe_calibrate_selected_axes(
        selected_origin: Optional[Vector],
        selected_orientation: Dict[str, Any],
        selected_lr: Vector,
        selected_ud: Vector,
        selected_fb: Vector,
        selected_source: str,
    ) -> Tuple[Vector, Vector, Vector, str]:
        if _normalize_axis_mode() != "auto":
            return selected_lr, selected_ud, selected_fb, selected_source
        if str(os.getenv("NANODRILL_ENABLE_AREA_TELEMETRY_AUTOCALIBRATION", "")).strip().lower() in {"1", "true", "yes", "on"}:
            print("  WARNING: diagnostic area.center auto-calibration is enabled. Do not use this for normal mining unless plugin area.center is known to match the visible Nanobot cube.")
            calibrated = _calibrate_axes_from_current_area(drill, selected_orientation, selected_origin)
            if calibrated is not None:
                selected_lr, selected_ud, selected_fb, calibration_source = calibrated
                selected_source = selected_source + "; " + calibration_source
            else:
                print("  Auto axis calibration unavailable; keeping v21 default axis_mode=left-up-forward")
        else:
            selected_source = selected_source + "; v21 default: auto=left-up-forward"
        return selected_lr, selected_ud, selected_fb, selected_source

    if priority == "device" and device_lr is not None and device_ud is not None and device_fb is not None:
        print("Transform diagnostics: using LIVE Nanobot device transform because NANODRILL_TRANSFORM_PRIORITY=device")
        if block_lr is not None and block_ud is not None and block_fb is not None:
            print("  grid block transform is present only for comparison")
            print(f"  block source:  {block_source}")
            print(f"  device source: {device_source}")
            print(f"  block_pos={_format_vec(block_pos)}")
            print(f"  device_pos={_format_vec(device_pos)}")
            if device_pos is not None and block_pos is not None:
                print(f"  device/block position gap: {v_len(v_sub(device_pos, block_pos)):.3f}m")
            print(
                "  axis comparison dot products: "
                f"LR={v_dot(device_lr, block_lr):+.4f}, "
                f"UD={v_dot(device_ud, block_ud):+.4f}, "
                f"FB={v_dot(device_fb, block_fb):+.4f}"
            )

        origin = device_pos or block_pos
        if origin is None:
            raise RuntimeError("Nanobot device transform has orientation but no position; cannot calculate AreaOffset origin")

        device_orientation = (drill.telemetry or {}).get("orientation", {}) if isinstance((drill.telemetry or {}).get("orientation", {}), dict) else {}
        device_lr, device_ud, device_fb, device_source = maybe_calibrate_selected_axes(
            origin,
            device_orientation,
            device_lr,
            device_ud,
            device_fb,
            device_source,
        )
        print("  using Nanobot device position/orientation as authoritative AreaOffset frame")
        return origin, device_lr, device_ud, device_fb, device_source + "; origin=device-live"

    if block_lr is not None and block_ud is not None and block_fb is not None:
        if device_lr is not None and device_ud is not None and device_fb is not None:
            print("Transform diagnostics: both grid block and Nanobot device transforms are present; using grid block axes by default")
            print(f"  block source:  {block_source}")
            print(f"  device source: {device_source}")
            print(f"  block_pos={_format_vec(block_pos)}")
            print(f"  device_pos={_format_vec(device_pos)}")
            if device_pos is not None and block_pos is not None:
                print(f"  device/block position gap: {v_len(v_sub(device_pos, block_pos)):.3f}m")

        origin_source = str(os.getenv("NANODRILL_AREA_ORIGIN_SOURCE", "device")).strip().lower()
        if origin_source not in {"device", "block", "rc-local", "computed", "reported-center"}:
            raise RuntimeError("Unsupported NANODRILL_AREA_ORIGIN_SOURCE=%r. Use device, block, rc-local, or reported-center." % origin_source)

        if origin_source == "reported-center":
            derived_origin, derived_source = _origin_from_reported_area_center(drill, block_lr, block_ud, block_fb)
            if derived_origin is not None:
                print(f"  using AreaOffset origin from {derived_source}: {_format_vec(derived_origin)}")
                print("  WARNING: reported-center origin is diagnostic only; old plugin builds can compute area.center with the wrong LeftRight sign")
                if block_pos is not None:
                    print(f"  origin/block gap: {v_len(v_sub(derived_origin, block_pos)):.3f}m")
                if device_pos is not None:
                    print(f"  origin/device gap: {v_len(v_sub(derived_origin, device_pos)):.3f}m")
                return derived_origin, block_lr, block_ud, block_fb, block_source + "; origin=" + derived_source
            print("  WARNING: requested reported-center origin, but area.center/offset telemetry is unavailable; falling back to device/block origin")

        if origin_source == "block":
            origin = block_pos or device_pos
            print("  using grid block world_pos as AreaOffset origin because NANODRILL_AREA_ORIGIN_SOURCE=block")
        elif origin_source in {"rc-local", "computed"}:
            # get_navigation_frame() will replace this with the RC/world-frame
            # calculation after it has RC telemetry and block local offset. Keep
            # device/block as a temporary source so axis calibration can still be
            # printed for diagnostics.
            origin = device_pos or block_pos
            print("  will use RC telemetry + Nanobot local offset as AreaOffset origin because NANODRILL_AREA_ORIGIN_SOURCE=rc-local")
        else:
            origin = device_pos or block_pos
            print("  using Nanobot device position as AreaOffset origin because NANODRILL_AREA_ORIGIN_SOURCE=device")

        if origin is not None:
            if block_pos is not None:
                print(f"  origin/block gap: {v_len(v_sub(origin, block_pos)):.3f}m")
            if device_pos is not None:
                print(f"  origin/device gap: {v_len(v_sub(origin, device_pos)):.3f}m")

        if origin is None:
            raise RuntimeError("Nanobot grid block transform has orientation but no usable origin")

        block = get_block_info(grid, drill.device_id)
        orientation = get_block_orientation(block) if block is not None else {}
        block_lr, block_ud, block_fb, block_source = maybe_calibrate_selected_axes(
            origin,
            orientation,
            block_lr,
            block_ud,
            block_fb,
            block_source,
        )

        return origin, block_lr, block_ud, block_fb, block_source + "; origin=" + origin_source

    if device_lr is not None and device_ud is not None and device_fb is not None:
        print("WARNING: grid block transform is missing; using Nanobot device transform fallback")
        return device_pos or block_pos, device_lr, device_ud, device_fb, device_source

    return device_pos or block_pos, None, None, None, ""

def _legacy_offsets_from_grid_vector(local_left: float, local_up: float, local_forward: float) -> Tuple[float, float, float]:
    grid_vec = [local_left, local_up, local_forward]

    def remap(prop_name: str) -> float:
        axis, sign = LEGACY_DRILL_AXIS_MAP[prop_name]
        return grid_vec[axis] * sign

    front_back = remap("FrontBack")
    up_down = remap("UpDown")
    left_right = remap("LeftRight")
    return front_back, up_down, left_right


def get_navigation_frame(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice,
) -> Tuple[Vector, Vector, Vector, Vector]:
    """Return origin and axes for Nanobot AreaOffset calculations.

    Signature is intentionally compatible with old scripts:
        drill_world, left, up, fwd = get_navigation_frame(...)

    But after this fix the three axes are not the ship grid axes. They are the
    Nanobot area axes:
        left -> AreaOffsetLeftRight positive direction;
        up   -> AreaOffsetUpDown positive direction;
        fwd  -> AreaOffsetFrontBack positive direction.
    """
    rc_pos, grid_left, grid_up, grid_forward, grid_frame_source = _read_true_grid_frame_from_rc(grid, rc)
    print(f"Ship grid frame: {grid_frame_source}")

    drill_local = get_drill_local_offset(grid, drill, rc)
    fallback_drill_world: Optional[Vector]
    if drill_local is None:
        fallback_drill_world = None
        print("WARNING: Nanobot local position was not found in grid metadata")
    else:
        fallback_drill_world = _world_from_rc_local(rc_pos, grid_left, grid_up, grid_forward, drill_local)
        print(f"Drill local offset from RC metadata: {drill_local}")

    transform_priority = str(os.getenv("NANODRILL_TRANSFORM_PRIORITY", "ship-local")).strip().lower()
    if transform_priority == "ship-local":
        drill_block = get_block_info(grid, drill.device_id)
        drill_local_orientation = get_block_local_orientation(drill_block) if drill_block is not None else {}
        axes = _block_axes_from_grid_and_local_orientation(
            grid_left, grid_up, grid_forward, drill_local_orientation
        )
        if axes is None:
            print(
                "WARNING: ship-local Nanobot axes unavailable; falling back to live device/grid telemetry "
                f"(rc_local_origin={_format_vec(fallback_drill_world)}, local_orientation={drill_local_orientation})"
            )
        else:
            area_left_right, area_up_down, area_front_back, axes_source = axes

            # Critical v17 fix. The block local_position stored in grid metadata is
            # not the Nanobot AreaOffset origin. It is a grid/block reference point
            # and can be ~11.5m away from the origin used by the Nanobot terminal.
            # When the ship is rotated 180 degrees that fixed local error rotates
            # with the grid, so the same script starts pushing the area forward/up
            # into open space. Recover the real terminal origin from the current
            # reported area center and the current AreaOffset values:
            #
            #   origin = area.center - LR_axis*AreaOffsetLeftRight
            #                        - UD_axis*AreaOffsetUpDown
            #                        - FB_axis*AreaOffsetFrontBack
            #
            # This keeps the RC/ship rotation and Nanobot block local_orientation
            # for axes, but does not trust grid metadata as the terminal origin.
            trust_reported_origin = str(os.getenv("NANODRILL_TRUST_REPORTED_AREA_CENTER_ORIGIN", "")).strip().lower() in {"1", "true", "yes", "on"}
            reported_origin: Optional[Vector] = None
            reported_origin_source = ""
            if trust_reported_origin:
                print("  WARNING: trusting reported area.center for origin is diagnostic only. Old plugin telemetry mirrors LeftRight.")
                reported_origin, reported_origin_source = _origin_from_reported_area_center(
                    drill, area_left_right, area_up_down, area_front_back
                )
            else:
                print("  v22: not using reported area.center to recover origin or axis signs by default; old telemetry can use the wrong Z/FrontBack sign")

            live_origin, live_lr, live_ud, live_fb, live_source = _read_drill_transform(grid, drill)

            if live_origin is not None:
                drill_world = live_origin
                origin_source = "live Nanobot device/block position"
            elif reported_origin is not None:
                drill_world = reported_origin
                origin_source = reported_origin_source
            elif fallback_drill_world is not None:
                drill_world = fallback_drill_world
                origin_source = "RC position + Nanobot local block offset fallback (less accurate)"
            else:
                print(
                    "WARNING: ship-local Nanobot origin unavailable; falling back to live device/grid telemetry "
                    f"(rc_local_origin={_format_vec(fallback_drill_world)}, local_orientation={drill_local_orientation})"
                )
                drill_world = None

            if drill_world is not None:
                # v22 safety: do NOT auto-calibrate from reported area.center by
                # default. The current bug proves that old plugin telemetry can be
                # perfectly self-consistent while the visible cube is mirrored on
                # Z/FrontBack. Enable this only for diagnostics.
                if _normalize_axis_mode() == "auto" and str(os.getenv("NANODRILL_ENABLE_AREA_TELEMETRY_AUTOCALIBRATION", "")).strip().lower() in {"1", "true", "yes", "on"}:
                    print("  WARNING: using diagnostic area.center axis calibration; it may reintroduce the wrong FrontBack sign on old plugins")
                    pseudo_orientation = _orientation_dict_from_axes(area_left_right, area_up_down, area_front_back)
                    calibrated = _calibrate_axes_from_current_area(drill, pseudo_orientation, drill_world)
                    if calibrated is not None:
                        area_left_right, area_up_down, area_front_back, calibration_source = calibrated
                        axes_source = axes_source + "; " + calibration_source
                    else:
                        axes_source = axes_source + "; v22 default axis sign kept"
                else:
                    axes_source = axes_source + "; v22 default axis sign kept"

                transform_source = (
                    axes_source
                    + "; origin=" + origin_source + "; "
                    + grid_frame_source
                )
                print(f"Nanobot AreaOffset origin: {drill_world} ({transform_source})")
                if fallback_drill_world is not None:
                    print(
                        "  RC-local metadata origin comparison: "
                        f"rc_local={_format_vec(fallback_drill_world)}, "
                        f"used_origin={_format_vec(drill_world)}, "
                        f"gap={v_len(v_sub(fallback_drill_world, drill_world)):.3f}m"
                    )
                if live_origin is not None:
                    print(
                        "  live telemetry origin comparison: "
                        f"live={_format_vec(live_origin)}, "
                        f"used_origin={_format_vec(drill_world)}, "
                        f"gap={v_len(v_sub(live_origin, drill_world)):.3f}m, "
                        f"source={live_source}"
                    )
                print(f"Nanobot area axes from {transform_source}")
                print(f"  LeftRight/X axis: {area_left_right}")
                print(f"  UpDown/Y axis:    {area_up_down}")
                print(f"  FrontBack/Z axis: {area_front_back}")
                _print_axis_diagnostics(area_left_right, area_up_down, area_front_back)

                if live_lr is not None and live_ud is not None and live_fb is not None:
                    print(
                        "  live axis comparison dots: "
                        f"LR={v_dot(live_lr, area_left_right):+.4f}, "
                        f"UD={v_dot(live_ud, area_up_down):+.4f}, "
                        f"FB={v_dot(live_fb, area_front_back):+.4f}"
                    )
                return drill_world, area_left_right, area_up_down, area_front_back

    drill_world_raw, area_left_right, area_up_down, area_front_back, transform_source = _read_drill_transform(grid, drill)

    origin_source = str(os.getenv("NANODRILL_AREA_ORIGIN_SOURCE", "device")).strip().lower()
    if origin_source in {"rc-local", "computed"} and fallback_drill_world is not None:
        if drill_world_raw is not None:
            print(
                "  RC-local origin override: "
                f"rc_local={_format_vec(fallback_drill_world)}, telemetry_origin={_format_vec(drill_world_raw)}, "
                f"gap={v_len(v_sub(fallback_drill_world, drill_world_raw)):.3f}m"
            )
        drill_world_raw = fallback_drill_world
        transform_source = transform_source + "; origin=rc-local-from-ship-position-and-block-local-offset"

    drill_world = drill_world_raw or fallback_drill_world

    if drill_world is None:
        # Last-resort legacy fallback: old scripts used this hardcoded offset.
        drill_local = (-2.5, 2.5, 5.0)
        drill_world = _world_from_rc_local(rc_pos, grid_left, grid_up, grid_forward, drill_local)
        print(f"WARNING: using legacy Nanobot local offset fallback: {drill_local}")
    elif drill_world_raw is not None:
        print(f"Nanobot AreaOffset origin: {drill_world} ({transform_source})")
    else:
        print(f"Nanobot AreaOffset origin from RC + block metadata: {drill_world}")

    if area_left_right is not None and area_up_down is not None and area_front_back is not None:
        print(f"Nanobot area axes from {transform_source}")
        print(f"  LeftRight axis: {area_left_right}")
        print(f"  UpDown axis:    {area_up_down}")
        print(f"  FrontBack axis: {area_front_back}")
        _print_axis_diagnostics(area_left_right, area_up_down, area_front_back)
        return drill_world, area_left_right, area_up_down, area_front_back

    if str(os.getenv("NANODRILL_ALLOW_LEGACY_AREA_MAP", "")).strip().lower() in {"1", "true", "yes", "on"}:
        print("WARNING: Nanobot orientation telemetry is missing; using UNSAFE legacy fixed axis map")
        legacy_left_right = grid_left
        legacy_up_down = grid_forward
        legacy_front_back = grid_up
        return drill_world, legacy_left_right, legacy_up_down, legacy_front_back

    raise RuntimeError(
        "Nanobot orientation telemetry is missing. Python refused to use the old fixed "
        "AreaOffset axis map because it can aim the Nanobot area into empty space when "
        "the block is mounted with another rotation. Update the DedicatedPlugin so either "
        "Nanobot device telemetry contains position/orientation/area.axis, or grid block "
        "telemetry contains blocks[].world_pos and blocks[].orientation. For one-time "
        "manual diagnostics only, set NANODRILL_ALLOW_LEGACY_AREA_MAP=1."
    )


def drill_offsets_from_local_vector(
    local_left_right: float,
    local_up_down: float,
    local_front_back: float,
) -> Tuple[float, float, float]:
    """Convert already Nanobot-local components to terminal property order."""
    return local_front_back, local_up_down, local_left_right


def grid_vector_from_drill_offsets(
    frontback: float,
    updown: float,
    leftright: float,
) -> Vector:
    """Legacy compatibility helper used by old diagnostics.

    In the new dynamic frame this returns an AreaOffset-local vector in the same
    order that old code called grid vector: (LeftRight, UpDown, FrontBack).
    """
    return leftright, updown, frontback


def _set_area_offsets_and_size(
    drill: NanobotDrillSystemDevice,
    *,
    front_back: float,
    up_down: float,
    left_right: float,
    area_size: float,
    delay: float,
) -> None:
    try:
        drill.set_raw_property("Drill.AreaOffsetFrontBack", round(front_back, 2))
        time.sleep(delay)
        drill.set_raw_property("Drill.AreaOffsetUpDown", round(up_down, 2))
        time.sleep(delay)
        drill.set_raw_property("Drill.AreaOffsetLeftRight", round(left_right, 2))
        time.sleep(delay)

        drill.set_raw_property("Drill.AreaWidth", float(area_size))
        time.sleep(delay)
        drill.set_raw_property("Drill.AreaHeight", float(area_size))
        time.sleep(delay)
        drill.set_raw_property("Drill.AreaDepth", float(area_size))
        time.sleep(delay)
    except Exception as exc:
        raise RuntimeError(f"Failed to set Nanobot area properties: {exc}") from exc


def _read_area_center_offsets_sizes(
    drill: NanobotDrillSystemDevice,
) -> Tuple[Optional[Vector], Optional[Tuple[float, float, float]], Dict[str, Optional[float]]]:
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
    actual_center = point_from_any(area.get("center") or area.get("Center"))
    actual_offsets = _area_offsets_from_telemetry(drill, area)
    actual_sizes = _area_sizes_from_telemetry(drill, area)
    return actual_center, actual_offsets, actual_sizes



def _has_v22_visible_area_center_telemetry(drill: NanobotDrillSystemDevice) -> bool:
    telemetry = drill.telemetry or {}
    version = str(telemetry.get("nanodrillTransformTelemetryVersion", "")).strip().lower()
    return "v22" in version or "fb_backward" in version

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
    """Aim Nanobot area center at a world coordinate.

    `left`, `up`, `fwd` are compatibility names. They must be the AreaOffset
    axes returned by get_navigation_frame().

    v22 keeps closed-loop correction disabled by default. The area.center read
    can be wrong on old plugin builds because the helper may use Forward while
    the visible Nanobot cube uses Backward. Mining success is validated through
    real Nanobot targets/inventory growth.
    """
    delta = v_sub(target_world, drill_world)

    local_left_right = v_dot(delta, left)
    local_up_down = v_dot(delta, up)
    local_front_back = v_dot(delta, fwd)

    drill_fb, drill_ud, drill_lr = drill_offsets_from_local_vector(
        local_left_right,
        local_up_down,
        local_front_back,
    )

    _set_area_offsets_and_size(
        drill,
        front_back=drill_fb,
        up_down=drill_ud,
        left_right=drill_lr,
        area_size=area_size,
        delay=delay,
    )

    # Closed-loop correction: if the live area center does not match the target,
    # project the residual onto the same AreaOffset axes and add it directly to
    # the terminal offsets. Usually one iteration fixes the persistent ~11.5m
    # miss caused by the wrong RC-local origin.
    # v22: default OFF. Closed-loop is a diagnostic tool only; area.center can
    # be self-consistent but visually wrong on old plugin builds.
    correction_enabled = str(os.getenv("NANODRILL_AREA_CLOSED_LOOP", "0")).strip().lower() in {"1", "true", "yes", "on"}
    correction_tolerance = float(os.getenv("NANODRILL_AREA_CLOSED_LOOP_TOLERANCE", "1.5") or "1.5")
    correction_iterations = max(0, int(float(os.getenv("NANODRILL_AREA_CLOSED_LOOP_ITERATIONS", "3") or "3")))

    actual_center: Optional[Vector] = None
    actual_offsets: Optional[Tuple[float, float, float]] = None
    actual_sizes: Dict[str, Optional[float]] = {"width": None, "height": None, "depth": None}
    telemetry_center_error: Optional[float] = None

    if correction_enabled and correction_iterations > 0:
        for iteration in range(1, correction_iterations + 1):
            actual_center, actual_offsets, actual_sizes = _read_area_center_offsets_sizes(drill)
            if actual_center is None or actual_offsets is None:
                break

            telemetry_center_error = v_len(v_sub(actual_center, target_world))
            if telemetry_center_error <= correction_tolerance:
                break

            actual_fb, actual_ud, actual_lr = actual_offsets
            residual = v_sub(target_world, actual_center)
            corr_lr = v_dot(residual, left)
            corr_ud = v_dot(residual, up)
            corr_fb = v_dot(residual, fwd)

            new_fb = actual_fb + corr_fb
            new_ud = actual_ud + corr_ud
            new_lr = actual_lr + corr_lr
            print(
                "  Area closed-loop correction "
                f"#{iteration}: center_error={telemetry_center_error:.3f}m, "
                f"residual=({residual[0]:+.3f},{residual[1]:+.3f},{residual[2]:+.3f}), "
                f"dFB={corr_fb:+.2f}, dUD={corr_ud:+.2f}, dLR={corr_lr:+.2f}; "
                f"new FB={new_fb:+.2f}, UD={new_ud:+.2f}, LR={new_lr:+.2f}"
            )
            _set_area_offsets_and_size(
                drill,
                front_back=new_fb,
                up_down=new_ud,
                left_right=new_lr,
                area_size=area_size,
                delay=delay,
            )
            drill_fb, drill_ud, drill_lr = new_fb, new_ud, new_lr

    # Final telemetry read for diagnostics.
    actual_center, actual_offsets, actual_sizes = _read_area_center_offsets_sizes(drill)
    if actual_center is not None:
        telemetry_center_error = v_len(v_sub(actual_center, target_world))

    estimated_center = v_add(
        drill_world,
        v_add(v_mul(left, drill_lr), v_add(v_mul(up, drill_ud), v_mul(fwd, drill_fb))),
    )
    center_error = v_len(v_sub(estimated_center, target_world))

    has_v22_center = _has_v22_visible_area_center_telemetry(drill)
    center_error_label = "actual_center_error" if has_v22_center else "plugin_center_error"
    verify_text = ""
    if telemetry_center_error is not None:
        verify_text = f" {center_error_label}={telemetry_center_error:.3f}m"

    print(
        "Area aim: "
        f"target=({target_world[0]:.2f}, {target_world[1]:.2f}, {target_world[2]:.2f}) "
        f"origin=({drill_world[0]:.2f}, {drill_world[1]:.2f}, {drill_world[2]:.2f}) "
        f"delta=({delta[0]:+.2f}, {delta[1]:+.2f}, {delta[2]:+.2f}) "
        f"FB={drill_fb:+.2f} UD={drill_ud:+.2f} LR={drill_lr:+.2f} "
        f"dist={v_len(delta):.2f}m center_error={center_error:.3f}m"
        f"{verify_text}"
    )
    print(
        "  Area axes: "
        f"LR=({left[0]:+.3f},{left[1]:+.3f},{left[2]:+.3f}) "
        f"UD=({up[0]:+.3f},{up[1]:+.3f},{up[2]:+.3f}) "
        f"FB=({fwd[0]:+.3f},{fwd[1]:+.3f},{fwd[2]:+.3f}) "
        f"estimated_center=({estimated_center[0]:.2f}, {estimated_center[1]:.2f}, {estimated_center[2]:.2f})"
    )
    print(
        "  Area local components: "
        f"LR={local_left_right:+.3f}, UD={local_up_down:+.3f}, FB={local_front_back:+.3f}; "
        f"final LR={drill_lr:+.2f}, UD={drill_ud:+.2f}, FB={drill_fb:+.2f}"
    )
    if actual_offsets is not None:
        actual_fb, actual_ud, actual_lr = actual_offsets
        print(
            "  Telemetry after set: "
            f"offsets FB={actual_fb:+.2f}, UD={actual_ud:+.2f}, LR={actual_lr:+.2f}; "
            f"sizes W={actual_sizes.get('width')}, H={actual_sizes.get('height')}, D={actual_sizes.get('depth')}; "
            f"center={_format_vec(actual_center)}"
        )
        if actual_center is not None:
            actual_local_delta = v_sub(target_world, actual_center)
            print(
                "  Target relative to telemetry center: "
                f"world_delta=({actual_local_delta[0]:+.3f},{actual_local_delta[1]:+.3f},{actual_local_delta[2]:+.3f}), "
                f"LR={v_dot(actual_local_delta, left):+.3f}, "
                f"UD={v_dot(actual_local_delta, up):+.3f}, "
                f"FB={v_dot(actual_local_delta, fwd):+.3f}"
            )

    if telemetry_center_error is not None:
        tolerance = max(5.0, min(20.0, float(area_size) * 0.25))
        if telemetry_center_error > tolerance:
            if has_v22_center:
                print(
                    f"WARNING: Nanobot area telemetry center is {telemetry_center_error:.2f}m from target. "
                    f"This can mean the mod has not updated the area yet or the point is bad."
                )
            else:
                print(
                    f"NOTE: plugin area.center is {telemetry_center_error:.2f}m from target, but this plugin "
                    f"does not advertise v22/fb_backward telemetry. Older helper telemetry can use the old "
                    f"Forward Z sign while the visible Nanobot cube uses Backward. Trust real targets/current "
                    f"voxel/inventory growth more than plugin_center_error, or rebuild the v22 DedicatedPlugin."
                )

    return drill_fb, drill_ud, drill_lr, v_len(delta)




NavigationFrameCandidate = Tuple[str, Vector, Vector, Vector, Vector]


def get_navigation_frame_candidates(
    grid: Grid,
    drill: NanobotDrillSystemDevice,
    rc: RemoteControlDevice,
    *,
    max_candidates: int = 0,
    include_permutations: bool = True,
) -> List[NavigationFrameCandidate]:
    """Return alternative AreaOffset frames for live empirical probing.

    This is intentionally independent from plugin-reported ``area.center``.
    The reported center can be produced by the helper plugin formula and can be
    self-consistent while the Nanobot mod renders the real area somewhere else.

    Each candidate is:
        (label, origin, lr_axis, ud_axis, fb_axis)

    The caller can set a candidate, briefly power the Nanobot in strict Collect
    mode, and keep the first mapping that actually produces requested-ore targets
    or raw-ore inventory growth. That calibrates against the real mod behavior,
    not against our helper telemetry.
    """
    rc_pos, grid_left, grid_up, grid_forward, _grid_frame_source = _read_true_grid_frame_from_rc(grid, rc)
    drill_local = get_drill_local_offset(grid, drill, rc)
    rc_local_origin: Optional[Vector] = None
    if drill_local is not None:
        rc_local_origin = _world_from_rc_local(rc_pos, grid_left, grid_up, grid_forward, drill_local)

    block = get_block_info(grid, drill.device_id)
    block_pos = get_block_world_position(block) if block is not None else None
    block_orientation = get_block_orientation(block) if block is not None else {}

    device_pos, _device_lr, _device_ud, _device_fb, _device_source = _read_drill_transform_from_device(drill)
    device_orientation = (drill.telemetry or {}).get("orientation", {}) if isinstance((drill.telemetry or {}).get("orientation", {}), dict) else {}

    orientation = block_orientation or device_orientation
    if not orientation:
        return []

    origins: List[Tuple[str, Vector]] = []
    origin_source = str(os.getenv("NANODRILL_AREA_ORIGIN_SOURCE", "device")).strip().lower()
    preferred_order = [origin_source, "device", "block", "rc-local"]
    seen_origin_names = set()
    for name in preferred_order:
        if name in seen_origin_names:
            continue
        seen_origin_names.add(name)
        if name == "device" and device_pos is not None:
            origins.append(("device", device_pos))
        elif name == "block" and block_pos is not None:
            origins.append(("block", block_pos))
        elif name in {"rc-local", "computed"} and rc_local_origin is not None:
            origins.append(("rc-local", rc_local_origin))

    if not origins:
        return []

    named_modes = [
        "left-up-forward",
        "right-up-forward",
        "left-up-backward",
        "right-up-backward",
        "left-down-forward",
        "right-down-forward",
        "left-forward-up",
        "right-forward-up",
        "left-backward-up",
        "right-backward-up",
        "up-left-forward",
        "up-right-forward",
        "forward-up-left",
        "forward-up-right",
        "backward-up-left",
        "backward-up-right",
    ]

    mappings: List[Tuple[str, Vector, Vector, Vector]] = []
    seen_axes = set()

    def add_mapping(label: str, lr: Optional[Vector], ud: Optional[Vector], fb: Optional[Vector]) -> None:
        if lr is None or ud is None or fb is None:
            return
        key = (
            round(lr[0], 6), round(lr[1], 6), round(lr[2], 6),
            round(ud[0], 6), round(ud[1], 6), round(ud[2], 6),
            round(fb[0], 6), round(fb[1], 6), round(fb[2], 6),
        )
        if key in seen_axes:
            return
        seen_axes.add(key)
        mappings.append((label, lr, ud, fb))

    # Current configured/calibrated mode first for continuity.
    cur_lr, cur_ud, cur_fb = _axes_from_orientation(orientation)
    add_mapping("configured-" + _normalize_axis_mode(), cur_lr, cur_ud, cur_fb)

    for mode in named_modes:
        lr, ud, fb = _axes_for_named_mode(orientation, mode)
        add_mapping(mode, lr, ud, fb)

    if include_permutations:
        for label, lr, ud, fb in _candidate_area_axis_mappings(orientation):
            add_mapping(label.replace(",", ";"), lr, ud, fb)

    candidates: List[NavigationFrameCandidate] = []
    seen_full = set()
    for origin_name, origin in origins:
        for mapping_label, lr, ud, fb in mappings:
            label = f"origin={origin_name};{mapping_label}"
            key = (origin_name, mapping_label)
            if key in seen_full:
                continue
            seen_full.add(key)
            candidates.append((label, origin, lr, ud, fb))

    if max_candidates and max_candidates > 0:
        return candidates[:max_candidates]
    return candidates

def world_from_base_and_local_offset(
    base_world: Vector,
    left: Vector,
    up: Vector,
    fwd: Vector,
    offset: Vector,
) -> Vector:
    local_left_right, local_up_down, local_front_back = offset
    return v_add(
        base_world,
        v_add(
            v_mul(left, local_left_right),
            v_add(v_mul(up, local_up_down), v_mul(fwd, local_front_back)),
        ),
    )
