#!/usr/bin/env python3
"""Load a Space Engineers clone blueprint and place it by projector offset.

The script prepares a blueprint for autonomous ship cloning. It uses a Merge
Block and a Connector as the contact key, then loads the blueprint into the
selected projector and applies ProjectionOffset so the projected Merge Block and
Connector are placed exactly at the calculated contact position.

Default behaviour is safe for cloning next to the current ship. The paired SE plugin must apply embedded ProjectionOffset/ProjectionRotation before SetProjectedGrid:
- choose the same Merge/Connector pair on the live grid by EntityId when possible;
- pre-flip the blueprint 180 degrees around the Merge/Connector line so the clone
  grows away from the source ship;
- choose an adjacent contact side with the least collision against the live grid;
- apply the final placement via projector.set_offset(), not by moving the whole
  blueprint into live grid coordinates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from dataclasses import dataclass
from itertools import permutations, product
from pathlib import Path
from typing import Callable, Iterable, Optional, TypeVar
import xml.etree.ElementTree as ET


XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
ET.register_namespace("xsi", XSI_NS)
ET.register_namespace("xsd", XSD_NS)

SCRIPT_VERSION = "align-clone-projection-offset-v44-forward-contact-2026-06-08"

DIRECTION_TO_VEC: dict[str, tuple[int, int, int]] = {
    "Right": (1, 0, 0),
    "Left": (-1, 0, 0),
    "Up": (0, 1, 0),
    "Down": (0, -1, 0),
    "Backward": (0, 0, 1),
    "Forward": (0, 0, -1),
}
VEC_TO_DIRECTION = {value: key for key, value in DIRECTION_TO_VEC.items()}
UNIT_AXES = {
    "x": ("x", 1),
    "+x": ("x", 1),
    "-x": ("x", -1),
    "y": ("y", 1),
    "+y": ("y", 1),
    "-y": ("y", -1),
    "z": ("z", 1),
    "+z": ("z", 1),
    "-z": ("z", -1),
}

ESSENTIAL_BLOCK_TAGS = {
    "SubtypeName",
    "Min",
    "BlockOrientation",
    "ColorMaskHSV",
    "SkinSubtypeId",
    "Owner",
    "BuiltBy",
    "ShareMode",
    "EntityId",
    "Enabled",
    "ProjectionOffset",
    "ProjectionRotation",
    "KeepProjection",
    "ShowOnlyBuildable",
    "InstantBuildingEnabled",
    "MaxNumberOfProjections",
    "MaxNumberOfBlocks",
    "GetOwnershipFromProjector",
    "Scale",
    "CustomName",
}


@dataclass(frozen=True)
class Vec3i:
    x: int
    y: int
    z: int

    def __add__(self, other: "Vec3i") -> "Vec3i":
        return Vec3i(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3i") -> "Vec3i":
        return Vec3i(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, value: int) -> "Vec3i":
        return Vec3i(self.x * value, self.y * value, self.z * value)

    def __neg__(self) -> "Vec3i":
        return Vec3i(-self.x, -self.y, -self.z)

    def as_tuple(self) -> tuple[int, int, int]:
        return self.x, self.y, self.z

    def manhattan(self) -> int:
        return abs(self.x) + abs(self.y) + abs(self.z)

    def dot(self, other: "Vec3i") -> int:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def axis_name(self) -> Optional[str]:
        active = [("x", self.x), ("y", self.y), ("z", self.z)]
        active = [(name, value) for name, value in active if value != 0]
        if len(active) != 1:
            return None
        return active[0][0]

    def __str__(self) -> str:
        return f"({self.x}, {self.y}, {self.z})"


@dataclass
class BlueprintBlock:
    element: ET.Element
    block_type: str
    subtype: str
    entity_id: Optional[int]
    name: str
    min: Vec3i


@dataclass(frozen=True)
class ContactPair:
    merge: BlueprintBlock
    connector: BlueprintBlock

    @property
    def vector(self) -> Vec3i:
        return self.connector.min - self.merge.min


@dataclass(frozen=True)
class LiveBlock:
    block_type: str
    subtype: str
    entity_id: Optional[int]
    name: str
    min: Vec3i
    orientation_forward: Optional[Vec3i] = None
    orientation_up: Optional[Vec3i] = None
    local_position_m: Optional[tuple[float, float, float]] = None
    world_position_m: Optional[tuple[float, float, float]] = None
    relative_to_grid_center_m: Optional[tuple[float, float, float]] = None
    world_axes: Optional[dict[str, tuple[float, float, float]]] = None


@dataclass(frozen=True)
class LiveContactPair:
    merge: LiveBlock
    connector: LiveBlock

    @property
    def vector(self) -> Vec3i:
        return self.connector.min - self.merge.min


@dataclass(frozen=True)
class PlacementCandidate:
    normal: Vec3i
    target_merge: Vec3i
    target_connector: Vec3i
    offset: Vec3i
    collisions: int
    predicted_center_score: int


T = TypeVar("T")
Rotation = Callable[[Vec3i], Vec3i]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xsi_type(element: ET.Element) -> str:
    return str(element.attrib.get(f"{{{XSI_NS}}}type") or element.attrib.get("xsi:type") or local_name(element.tag) or "")


def child_text(element: ET.Element, tag: str, default: str = "") -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def parse_int(text: object) -> Optional[int]:
    if text is None:
        return None
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def read_min(element: ET.Element) -> Optional[Vec3i]:
    min_el = element.find("Min")
    if min_el is None:
        return None
    x = parse_int(min_el.attrib.get("x"))
    y = parse_int(min_el.attrib.get("y"))
    z = parse_int(min_el.attrib.get("z"))
    if x is None or y is None or z is None:
        return None
    return Vec3i(x, y, z)


def set_min(element: ET.Element, value: Vec3i) -> None:
    min_el = element.find("Min")
    if min_el is None:
        min_el = ET.Element("Min")
        subtype = element.find("SubtypeName")
        insert_at = 1 if subtype is not None else 0
        element.insert(insert_at, min_el)
    min_el.attrib["x"] = str(value.x)
    min_el.attrib["y"] = str(value.y)
    min_el.attrib["z"] = str(value.z)


def get_or_create_orientation(element: ET.Element) -> ET.Element:
    orientation = element.find("BlockOrientation")
    if orientation is not None:
        return orientation
    orientation = ET.Element("BlockOrientation")
    orientation.attrib["Forward"] = "Forward"
    orientation.attrib["Up"] = "Up"
    min_el = element.find("Min")
    if min_el is not None:
        children = list(element)
        element.insert(children.index(min_el) + 1, orientation)
    else:
        subtype = element.find("SubtypeName")
        insert_at = 1 if subtype is not None else 0
        element.insert(insert_at, orientation)
    return orientation


def ensure_projection_vector(parent: ET.Element, tag: str, value: Vec3i) -> None:
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    for axis, number in (("X", value.x), ("Y", value.y), ("Z", value.z)):
        axis_node = node.find(axis)
        if axis_node is None:
            axis_node = ET.SubElement(node, axis)
        axis_node.text = str(number)


def update_orientation(element: ET.Element, rotation: Rotation) -> None:
    orientation = get_or_create_orientation(element)
    forward_name = orientation.attrib.get("Forward", "Forward")
    up_name = orientation.attrib.get("Up", "Up")
    forward_vec = DIRECTION_TO_VEC.get(forward_name, DIRECTION_TO_VEC["Forward"])
    up_vec = DIRECTION_TO_VEC.get(up_name, DIRECTION_TO_VEC["Up"])
    new_forward = rotation(Vec3i(*forward_vec)).as_tuple()
    new_up = rotation(Vec3i(*up_vec)).as_tuple()
    if new_forward not in VEC_TO_DIRECTION or new_up not in VEC_TO_DIRECTION:
        raise ValueError(f"rotation produced invalid orientation for {child_text(element, 'SubtypeName', '?')}")
    orientation.attrib["Forward"] = VEC_TO_DIRECTION[new_forward]
    orientation.attrib["Up"] = VEC_TO_DIRECTION[new_up]


def vec_abs(value: Vec3i) -> Vec3i:
    return Vec3i(abs(value.x), abs(value.y), abs(value.z))


def vec_cross(a: Vec3i, b: Vec3i) -> Vec3i:
    return Vec3i(
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    )


# Only sizes that matter for robust Min transformation are listed here.
# Unknown blocks are treated as 1x1x1, which is safe for contact blocks and
# avoids corrupting modded blocks with guessed dimensions.
BLOCK_SIZE_OVERRIDES: dict[tuple[str, str], Vec3i] = {
    ("myobjectbuilder_cargocontainer", "largeblocklargecontainer"): Vec3i(3, 3, 3),
    ("myobjectbuilder_oxygentank", "largehydrogentank"): Vec3i(3, 3, 3),
    ("myobjectbuilder_reactor", "largeblocklargegenerator"): Vec3i(2, 2, 2),
    ("myobjectbuilder_thrust", "largeblocksmallhydrogenthrust"): Vec3i(1, 1, 2),
    ("myobjectbuilder_thrust", "largeblocksmallthrust"): Vec3i(1, 1, 2),
    ("myobjectbuilder_hydrogenengine", "largehydrogenengine"): Vec3i(1, 1, 2),
    ("myobjectbuilder_oxygengenerator", ""): Vec3i(1, 1, 2),
    ("myobjectbuilder_oredetector", "largeoredetector"): Vec3i(1, 1, 2),
    ("myobjectbuilder_assembler", "largeassembler"): Vec3i(2, 1, 1),
    ("myobjectbuilder_refinery", "blast furnace"): Vec3i(1, 1, 2),
    ("myobjectbuilder_solarpanel", "largeblocksolarpanel"): Vec3i(4, 1, 1),
}


def block_local_size(block: BlueprintBlock) -> Vec3i:
    key = (block.block_type.lower(), block.subtype.lower())
    if key in BLOCK_SIZE_OVERRIDES:
        return BLOCK_SIZE_OVERRIDES[key]

    type_text = block.block_type.lower()
    subtype_text = block.subtype.lower()
    if "largecontainer" in subtype_text:
        return Vec3i(3, 3, 3)
    if "hydrogentank" in subtype_text:
        return Vec3i(3, 3, 3)
    if "largegenerator" in subtype_text:
        return Vec3i(2, 2, 2)
    if "smallhydrogenthrust" in subtype_text or "smallthrust" in subtype_text:
        return Vec3i(1, 1, 2)
    if "hydrogenengine" in type_text or "oxygengenerator" in type_text:
        return Vec3i(1, 1, 2)
    if "solar" in type_text or "solarpanel" in subtype_text:
        return Vec3i(4, 1, 1)
    return Vec3i(1, 1, 1)


def block_orientation_axes(element: ET.Element) -> tuple[Vec3i, Vec3i, Vec3i]:
    orientation = element.find("BlockOrientation")
    forward_name = orientation.attrib.get("Forward", "Forward") if orientation is not None else "Forward"
    up_name = orientation.attrib.get("Up", "Up") if orientation is not None else "Up"
    forward = Vec3i(*DIRECTION_TO_VEC.get(forward_name, DIRECTION_TO_VEC["Forward"]))
    up = Vec3i(*DIRECTION_TO_VEC.get(up_name, DIRECTION_TO_VEC["Up"]))
    right = vec_cross(forward, up)
    if right.manhattan() != 1:
        right = Vec3i(1, 0, 0)
    return right, up, forward




def parse_axis_direction(value: object) -> Optional[Vec3i]:
    """Parse a block direction from SE names or an axis-aligned vector.

    Grid block telemetry is not fully stable across bridge versions: some
    payloads carry BlockOrientation names ("Forward", "Up"), while others carry
    vectors.  We only accept vectors that are already close to a grid axis.  A
    world-space vector of a rotated grid is intentionally rejected, because using
    it as a local block axis would create a wrong projection transform.
    """
    if isinstance(value, str):
        text = value.strip()
        if text in DIRECTION_TO_VEC:
            return Vec3i(*DIRECTION_TO_VEC[text])
        title = text[:1].upper() + text[1:].lower() if text else text
        if title in DIRECTION_TO_VEC:
            return Vec3i(*DIRECTION_TO_VEC[title])
        return None

    raw: list[float]
    if isinstance(value, dict):
        def read_component(*names: str) -> Optional[float]:
            for name in names:
                if name in value:
                    try:
                        return float(value[name])
                    except (TypeError, ValueError):
                        return None
            return None
        x = read_component("x", "X")
        y = read_component("y", "Y")
        z = read_component("z", "Z")
        if x is None or y is None or z is None:
            return None
        raw = [x, y, z]
    elif isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            raw = [float(value[0]), float(value[1]), float(value[2])]
        except (TypeError, ValueError):
            return None
    else:
        return None

    abs_values = [abs(item) for item in raw]
    best_index = max(range(3), key=lambda index: abs_values[index])
    best_value = abs_values[best_index]
    second_value = max(abs_values[index] for index in range(3) if index != best_index)
    if best_value < 0.70 or second_value > 0.35:
        return None
    sign = 1 if raw[best_index] >= 0 else -1
    if best_index == 0:
        return Vec3i(sign, 0, 0)
    if best_index == 1:
        return Vec3i(0, sign, 0)
    return Vec3i(0, 0, sign)


def read_orientation_pair_from_source(source: object) -> tuple[Optional[Vec3i], Optional[Vec3i]]:
    if not isinstance(source, dict):
        return None, None
    forward = (
        source.get("Forward")
        or source.get("forward")
        or source.get("fwd")
        or source.get("ForwardVector")
        or source.get("forwardVector")
    )
    up = source.get("Up") or source.get("up") or source.get("UpVector") or source.get("upVector")
    return parse_axis_direction(forward), parse_axis_direction(up)


def read_orientation_from_mapping(data: object) -> tuple[Optional[Vec3i], Optional[Vec3i]]:
    if not isinstance(data, dict):
        return None, None

    # IMPORTANT: grid telemetry contains two different orientation fields:
    #   local_orientation: cardinal block orientation in the grid frame, e.g.
    #                      {"forward": "Down", "up": "Backward"}
    #   orientation:       world-space floating vectors, e.g. {"forward": {x,y,z}, ...}
    # The projector placement math needs the local grid-frame orientation.
    # Older versions read ``orientation`` first, failed to snap world vectors to
    # grid axes, and silently fell back to identity axes for SmallProjector.
    for key in (
        "local_orientation",
        "localOrientation",
        "LocalOrientation",
        "blockOrientation",
        "BlockOrientation",
    ):
        forward, up = read_orientation_pair_from_source(data.get(key))
        if forward is not None and up is not None:
            return forward, up

    forward, up = read_orientation_pair_from_source(data)
    if forward is not None and up is not None:
        return forward, up

    # Last-resort fallback only. This may work for payloads where ``orientation``
    # is already expressed as cardinal grid axes; it intentionally stays after
    # local_orientation because world vectors are not valid grid-cell axes.
    for key in ("orientation", "Orientation"):
        forward, up = read_orientation_pair_from_source(data.get(key))
        if forward is not None and up is not None:
            return forward, up

    return None, None


def live_block_orientation(block: object) -> tuple[Optional[Vec3i], Optional[Vec3i]]:
    for source in (getattr(block, "extra", None), getattr(block, "state", None), block):
        forward, up = read_orientation_from_mapping(source)
        if forward is not None and up is not None:
            return forward, up
    return None, None


def orientation_to_text(forward: Optional[Vec3i], up: Optional[Vec3i]) -> str:
    if forward is None or up is None:
        return "?"
    f_name = VEC_TO_DIRECTION.get(forward.as_tuple(), str(forward))
    u_name = VEC_TO_DIRECTION.get(up.as_tuple(), str(up))
    return f"Forward={f_name} Up={u_name}"


def _float_tuple3(value: object) -> Optional[tuple[float, float, float]]:
    """Read a 3D vector from telemetry.

    Grid telemetry may encode vectors either as [x, y, z] arrays or as
    {"x": ..., "y": ..., "z": ...} dictionaries.  v31 only accepted
    arrays, therefore it printed world forward/up/right as "?" even though
    the raw grid JSON contained those vectors.
    """
    if isinstance(value, dict):
        try:
            return (
                float(value.get("x") if "x" in value else value.get("X")),
                float(value.get("y") if "y" in value else value.get("Y")),
                float(value.get("z") if "z" in value else value.get("Z")),
            )
        except (TypeError, ValueError):
            return None
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return float(value[0]), float(value[1]), float(value[2])
    except (TypeError, ValueError):
        return None


def _read_from_sources(block: object, key: str) -> object:
    if hasattr(block, key):
        value = getattr(block, key)
        if value is not None:
            return value
    for source in (getattr(block, "extra", None), getattr(block, "state", None)):
        if isinstance(source, dict) and key in source:
            return source.get(key)
    return None


def read_float3_from_block(block: object, *keys: str) -> Optional[tuple[float, float, float]]:
    for key in keys:
        parsed = _float_tuple3(_read_from_sources(block, key))
        if parsed is not None:
            return parsed
    return None


def read_world_axes_from_block(block: object) -> Optional[dict[str, tuple[float, float, float]]]:
    value = _read_from_sources(block, "orientation") or _read_from_sources(block, "Orientation")
    if not isinstance(value, dict):
        return None
    axes: dict[str, tuple[float, float, float]] = {}
    for name in ("forward", "backward", "up", "down", "right", "left"):
        parsed = _float_tuple3(value.get(name) or value.get(name.capitalize()))
        if parsed is not None:
            axes[name] = parsed
    return axes or None


def fmt_float3(value: Optional[tuple[float, float, float]], decimals: int = 3) -> str:
    if value is None:
        return "?"
    return f"({value[0]:.{decimals}f}, {value[1]:.{decimals}f}, {value[2]:.{decimals}f})"


def float3_add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def float3_sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def float3_scale(a: tuple[float, float, float], value: float) -> tuple[float, float, float]:
    return a[0] * value, a[1] * value, a[2] * value


def float3_len(a: tuple[float, float, float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def live_block_face_direction(block: LiveBlock) -> Optional[Vec3i]:
    return block.orientation_forward


def world_axis_from_vec3i(block: LiveBlock, value: Optional[Vec3i]) -> Optional[tuple[float, float, float]]:
    if value is None or block.world_axes is None:
        return None
    key = VEC_TO_DIRECTION.get(value.as_tuple())
    if key is None:
        return None
    return block.world_axes.get(key.lower())


def projector_local_vec_to_world(projector: LiveBlock, value: Vec3i, grid_step: float) -> Optional[tuple[float, float, float]]:
    axes = projector.world_axes
    if not axes:
        return None
    right = axes.get("right")
    up = axes.get("up")
    backward = axes.get("backward")
    if right is None or up is None or backward is None:
        return None
    return (
        (right[0] * value.x + up[0] * value.y + backward[0] * value.z) * grid_step,
        (right[1] * value.x + up[1] * value.y + backward[1] * value.z) * grid_step,
        (right[2] * value.x + up[2] * value.y + backward[2] * value.z) * grid_step,
    )


def predicted_world_from_projector_frame(
    projector: LiveBlock,
    blueprint_projector_min: Vec3i,
    block_min: Vec3i,
    offset: Vec3i,
    rotation_transform: Rotation,
    grid_step: float,
) -> Optional[tuple[float, float, float]]:
    if projector.world_position_m is None:
        return None
    projected_local = rotation_transform((block_min - blueprint_projector_min) + offset)
    delta_world = projector_local_vec_to_world(projector, projected_local, grid_step)
    if delta_world is None:
        return None
    return float3_add(projector.world_position_m, delta_world)


def print_live_block_debug(label: str, block: LiveBlock, *, grid_step: float) -> None:
    print(f"  {label}: {block.subtype or block.block_type} entity={block.entity_id or '?'} name={block.name or '?'}")
    print(f"    Min cells:          {block.min}")
    print(f"    Min as meters:      ({block.min.x * grid_step:.3f}, {block.min.y * grid_step:.3f}, {block.min.z * grid_step:.3f})")
    print(f"    telemetry local_pos:{fmt_float3(block.local_position_m)}")
    print(f"    world_pos:          {fmt_float3(block.world_position_m)}")
    print(f"    relative_center:    {fmt_float3(block.relative_to_grid_center_m)}")
    print(f"    local_orientation:  {orientation_to_text(block.orientation_forward, block.orientation_up)}")
    if block.world_axes:
        print(f"    world forward/up/right: f={fmt_float3(block.world_axes.get('forward'))} u={fmt_float3(block.world_axes.get('up'))} r={fmt_float3(block.world_axes.get('right'))}")
    else:
        print("    world forward/up/right: ?")


def print_live_contact_debug(
    *,
    projector: LiveBlock,
    live_pair: LiveContactPair,
    projector_to_grid: Rotation,
    grid_to_projector: Rotation,
    grid_step: float,
) -> None:
    print("Live contact debug:")
    print_live_block_debug("projector", projector, grid_step=grid_step)
    print_live_block_debug("merge", live_pair.merge, grid_step=grid_step)
    print_live_block_debug("connector", live_pair.connector, grid_step=grid_step)
    print(f"  live merge->connector cells:       {live_pair.vector}")
    print(f"  live merge->connector projector-local: {grid_to_projector(live_pair.vector)}")
    if live_pair.merge.world_position_m is not None and live_pair.connector.world_position_m is not None:
        delta = float3_sub(live_pair.connector.world_position_m, live_pair.merge.world_position_m)
        print(f"  live merge->connector world delta: {fmt_float3(delta)} len={float3_len(delta):.3f}m")
    if live_pair.merge.world_position_m is not None and projector.world_position_m is not None:
        delta = float3_sub(live_pair.merge.world_position_m, projector.world_position_m)
        print(f"  projector->live merge world delta: {fmt_float3(delta)} len={float3_len(delta):.3f}m")
    print(f"  projector axes grid: local X->{projector_to_grid(Vec3i(1, 0, 0))}, local Y->{projector_to_grid(Vec3i(0, 1, 0))}, local Z->{projector_to_grid(Vec3i(0, 0, 1))}")
    print("  live merge model-face candidates:")
    for face_name in MERGE_MATE_FACE_CHOICES:
        face_vec = live_model_face_vector(live_pair.merge, face_name)
        if face_vec is None:
            print(f"    {face_name:8s}: ?")
            continue
        valid = "valid-normal" if is_valid_contact_normal(face_vec, live_pair.vector) else "parallel-to-pair"
        face_world = world_axis_from_vec3i(projector, face_vec)
        print(f"    {face_name:8s}: grid={face_vec} world={fmt_float3(face_world)} {valid}")


def print_projection_contact_debug(
    *,
    live_projector: LiveBlock,
    blueprint_projector_min: Vec3i,
    blueprint_pair: ContactPair,
    live_pair: LiveContactPair,
    projector_offset: Vec3i,
    projection_rotation: Vec3i,
    final_merge: Vec3i,
    final_connector: Vec3i,
    final_projected_merge_face: Optional[Vec3i],
    grid_step: float,
) -> None:
    rotation_transform = projection_rotation_transform(projection_rotation)
    merge_projector_local = rotation_transform((blueprint_pair.merge.min - blueprint_projector_min) + projector_offset)
    connector_projector_local = rotation_transform((blueprint_pair.connector.min - blueprint_projector_min) + projector_offset)
    merge_world = predicted_world_from_projector_frame(live_projector, blueprint_projector_min, blueprint_pair.merge.min, projector_offset, rotation_transform, grid_step)
    connector_world = predicted_world_from_projector_frame(live_projector, blueprint_projector_min, blueprint_pair.connector.min, projector_offset, rotation_transform, grid_step)
    live_delta_cells = final_merge - live_pair.merge.min
    live_delta_world = projector_local_vec_to_world(live_projector, live_delta_cells, grid_step)
    print("Projected contact debug:")
    print("  NOTE: projected coordinates below are calculated from Python/projector math, not read back from game projection telemetry.")
    print(f"  blueprint projector anchor Min:       {blueprint_projector_min}")
    print(f"  blueprint merge original Min:         {blueprint_pair.merge.min}")
    print(f"  blueprint connector original Min:     {blueprint_pair.connector.min}")
    print(f"  ProjectionOffset/Rotation:            offset={projector_offset}, rotation={projection_rotation}")
    print(f"  projected merge projector-local cells:{merge_projector_local}")
    print(f"  projected conn. projector-local cells:{connector_projector_local}")
    print(f"  projected merge live-grid Min:        {final_merge}")
    print(f"  projected connector live-grid Min:    {final_connector}")
    print(f"  target live merge Min:                {live_pair.merge.min}")
    print(f"  target live connector Min:            {live_pair.connector.min}")
    print(f"  projected merge-live delta cells:     {final_merge - live_pair.merge.min}")
    print(f"  projected conn.-live delta cells:     {final_connector - live_pair.connector.min}")
    print(f"  projected merge-live delta world by cells: {fmt_float3(live_delta_world)}")
    print(f"  projected merge world approx:         {fmt_float3(merge_world)}")
    print(f"  projected connector world approx:     {fmt_float3(connector_world)}")
    if merge_world is not None and live_pair.merge.world_position_m is not None:
        delta = float3_sub(merge_world, live_pair.merge.world_position_m)
        print(f"  projected merge-live world delta:     {fmt_float3(delta)} len={float3_len(delta):.3f}m")
    if connector_world is not None and live_pair.connector.world_position_m is not None:
        delta = float3_sub(connector_world, live_pair.connector.world_position_m)
        print(f"  projected conn.-live world delta:     {fmt_float3(delta)} len={float3_len(delta):.3f}m")
    print(f"  projected merge face grid direction:  {final_projected_merge_face if final_projected_merge_face is not None else '?'}")
    if final_projected_merge_face is not None:
        face_world = world_axis_from_vec3i(live_projector, final_projected_merge_face)
        print(f"  projected merge face world approx:    {fmt_float3(face_world)}")


def print_projection_transform_audit(
    *,
    live_projector: LiveBlock,
    blueprint_projector_min: Vec3i,
    blueprint_pair: ContactPair,
    live_pair: LiveContactPair,
    offset: Vec3i,
    rotation: Vec3i,
    projector_to_grid: Rotation,
    grid_step: float,
) -> None:
    """Print several transform conventions side-by-side for diagnosis."""
    rot = projection_rotation_transform(rotation)
    rel_merge = blueprint_pair.merge.min - blueprint_projector_min
    rel_connector = blueprint_pair.connector.min - blueprint_projector_min

    def p1(rel: Vec3i) -> Vec3i:
        return live_projector.min + projector_to_grid(rot(rel + offset))

    def p2(rel: Vec3i) -> Vec3i:
        return live_projector.min + projector_to_grid(rot(rel) + offset)

    def p3(rel: Vec3i) -> Vec3i:
        return live_projector.min + projector_to_grid(rel + offset)

    variants = [
        ("A assumed game R(rel+offset)", p1),
        ("B alternative R(rel)+offset", p2),
        ("C no native rotation rel+offset", p3),
    ]
    print("Projection transform audit:")
    print(f"  live projector Min:       {live_projector.min}  local_pos={fmt_float3(live_projector.local_position_m)}  world={fmt_float3(live_projector.world_position_m)}")
    print(f"  live projector orient:    {orientation_to_text(live_projector.orientation_forward, live_projector.orientation_up)}")
    print(f"  projection offset/rot:    offset={offset}, rotation={rotation}")
    print(f"  blueprint rel merge:      {rel_merge}; rel connector: {rel_connector}")
    for label, func in variants:
        m = func(rel_merge)
        c = func(rel_connector)
        md = m - live_pair.merge.min
        cd = c - live_pair.connector.min
        mw = None
        if live_projector.world_position_m is not None:
            mw_delta = projector_local_vec_to_world(live_projector, m - live_projector.min, grid_step)
            if mw_delta is not None:
                mw = float3_add(live_projector.world_position_m, mw_delta)
        print(f"  {label}:")
        print(f"    merge={m}, connector={c}, pair={c - m}")
        print(f"    merge-live delta={md}, connector-live delta={cd}")
        print(f"    merge world approx={fmt_float3(mw)}")


def identity_rotation(value: Vec3i) -> Vec3i:
    return value


def projector_axis_transforms(
    forward: Optional[Vec3i],
    up: Optional[Vec3i],
) -> tuple[Rotation, Rotation, bool, str]:
    """Return projection-local <-> live-grid transforms for a projector block.

    Projection local axes are X=Right, Y=Up, Z=Backward relative to the projector
    block.  With a default projector orientation this is the identity mapping.
    """
    if forward is None or up is None:
        return identity_rotation, identity_rotation, False, "projector orientation unavailable; using identity grid axes"
    if forward.manhattan() != 1 or up.manhattan() != 1 or forward.dot(up) != 0:
        return identity_rotation, identity_rotation, False, f"invalid projector orientation {orientation_to_text(forward, up)}; using identity grid axes"
    right = vec_cross(forward, up)
    if right.manhattan() != 1:
        return identity_rotation, identity_rotation, False, f"invalid projector orientation {orientation_to_text(forward, up)}; using identity grid axes"
    backward = -forward

    def to_grid(value: Vec3i) -> Vec3i:
        return Vec3i(
            right.x * value.x + up.x * value.y + backward.x * value.z,
            right.y * value.x + up.y * value.y + backward.y * value.z,
            right.z * value.x + up.z * value.y + backward.z * value.z,
        )

    def to_projector(value: Vec3i) -> Vec3i:
        return Vec3i(value.dot(right), value.dot(up), value.dot(backward))

    message = f"projector axes: local X->{right}, local Y->{up}, local Z->{backward} from {orientation_to_text(forward, up)}"
    return to_grid, to_projector, True, message


def parse_direction_arg(value: str) -> Vec3i:
    parsed = parse_axis_direction(value)
    if parsed is None:
        valid = ", ".join(DIRECTION_TO_VEC)
        raise argparse.ArgumentTypeError(f"direction must be one of: {valid}")
    return parsed

MERGE_MATE_FACE_CHOICES = ("forward", "backward", "right", "left", "up", "down")


def model_face_vector_from_axes(right: Vec3i, up: Vec3i, forward: Vec3i, face: str) -> Vec3i:
    value = str(face or "forward").strip().lower()
    if value == "forward":
        return forward
    if value == "backward":
        return -forward
    if value == "right":
        return right
    if value == "left":
        return -right
    if value == "up":
        return up
    if value == "down":
        return -up
    raise ValueError(f"unsupported merge mate face: {face!r}")


def block_model_face_vector(block: BlueprintBlock, face: str = "forward") -> Vec3i:
    """Return a model-space face direction expressed in blueprint grid cells.

    Space Engineers block orientation maps the model axes Forward/Up/Right to
    grid directions. Earlier versions assumed that the Merge Block mating face
    is always model Forward. This diagnostic version can try all six model
    faces because mods/game blocks may expose their terminal orientation in a
    way that differs from the actual visible merge plate.
    """
    right, up, forward = block_orientation_axes(block.element)
    return model_face_vector_from_axes(right, up, forward, face)


def live_model_face_vector(block: LiveBlock, face: str = "forward") -> Optional[Vec3i]:
    forward = block.orientation_forward
    up = block.orientation_up
    if forward is None or up is None:
        return None
    right = vec_cross(forward, up)
    if right.manhattan() != 1:
        return None
    return model_face_vector_from_axes(right, up, forward, face)


def is_valid_contact_normal(normal: Vec3i, contact_vector: Vec3i) -> bool:
    return normal.manhattan() == 1 and contact_vector.dot(normal) == 0


def resolve_auto_contact_normals(
    contact_vector: Vec3i,
    normal_text: str,
    preferred_normal: Optional[Vec3i] = None,
) -> list[Vec3i]:
    if normal_text != "auto":
        return normal_candidates(contact_vector, normal_text)
    if preferred_normal is not None and is_valid_contact_normal(preferred_normal, contact_vector):
        return [preferred_normal]
    return normal_candidates(contact_vector, normal_text)


def block_axis_aligned_span(block: BlueprintBlock) -> Vec3i:
    size = block_local_size(block)
    right, up, forward = block_orientation_axes(block.element)
    ar = vec_abs(right)
    au = vec_abs(up)
    af = vec_abs(forward)
    return Vec3i(
        ar.x * size.x + au.x * size.y + af.x * size.z,
        ar.y * size.x + au.y * size.y + af.y * size.z,
        ar.z * size.x + au.z * size.y + af.z * size.z,
    )


def occupied_cells_from_min(block: BlueprintBlock) -> list[Vec3i]:
    span = block_axis_aligned_span(block)
    cells: list[Vec3i] = []
    for dx in range(max(1, span.x)):
        for dy in range(max(1, span.y)):
            for dz in range(max(1, span.z)):
                cells.append(Vec3i(block.min.x + dx, block.min.y + dy, block.min.z + dz))
    return cells


def transform_block_min_by_occupied_cells(block: BlueprintBlock, position_transform: Rotation) -> Vec3i:
    transformed = [position_transform(cell) for cell in occupied_cells_from_min(block)]
    return Vec3i(
        min(cell.x for cell in transformed),
        min(cell.y for cell in transformed),
        min(cell.z for cell in transformed),
    )


def is_connector_type(block_type: str, subtype: str) -> bool:
    text = f"{block_type} {subtype}".lower()
    return "shipconnector" in text or "connector" in text


def is_merge_type(block_type: str, subtype: str) -> bool:
    text = f"{block_type} {subtype}".lower()
    return "mergeblock" in text or "merge block" in text or "merge" in text


def is_projector_type(block_type: str, subtype: str) -> bool:
    text = f"{block_type} {subtype}".lower()
    return "projector" in text


def resolve_blueprint_path(path_text: str) -> tuple[Path, Optional[tempfile.TemporaryDirectory[str]]]:
    path = Path(path_text).expanduser().resolve()
    if path.is_dir():
        bp = path / "bp.sbc"
        if bp.exists():
            return bp, None
        candidates = sorted(path.rglob("bp.sbc"))
        if candidates:
            return candidates[0], None
        raise FileNotFoundError(f"directory does not contain bp.sbc: {path}")

    if not path.exists():
        raise FileNotFoundError(f"blueprint file does not exist: {path}")

    if path.suffix.lower() == ".zip":
        temp = tempfile.TemporaryDirectory(prefix="se_bp_")
        with zipfile.ZipFile(path, "r") as archive:
            names = [name for name in archive.namelist() if name.replace("\\", "/").endswith("bp.sbc")]
            if not names:
                temp.cleanup()
                raise FileNotFoundError(f"zip does not contain bp.sbc: {path}")
            selected = sorted(names, key=lambda name: (name.count("/"), name))[0]
            archive.extract(selected, temp.name)
        return Path(temp.name) / selected, temp

    return path, None


def parse_blueprint_text(data: str) -> ET.ElementTree:
    root = ET.fromstring(data)

    if local_name(root.tag) == "MyObjectBuilder_ShipBlueprintDefinition":
        return ET.ElementTree(root)

    ship = None
    if local_name(root.tag) == "ShipBlueprint":
        ship = root
    else:
        for candidate in root.iter():
            if local_name(candidate.tag) == "ShipBlueprint":
                type_name = xsi_type(candidate)
                if type_name == "MyObjectBuilder_ShipBlueprintDefinition" or candidate.find("CubeGrids") is not None:
                    ship = candidate
                    break

    if ship is None:
        raise ValueError("blueprint XML does not contain ShipBlueprint/MyObjectBuilder_ShipBlueprintDefinition")

    new_root = ET.Element("MyObjectBuilder_ShipBlueprintDefinition")
    for key, value in ship.attrib.items():
        if key.endswith("}type") or key == "xsi:type":
            continue
        new_root.attrib[key] = value
    new_root.attrib["xmlns:xsd"] = XSD_NS
    for child in list(ship):
        new_root.append(copy.deepcopy(child))
    return ET.ElementTree(new_root)


def parse_blueprint(path: Path) -> ET.ElementTree:
    data = path.read_text(encoding="utf-8-sig", errors="replace")
    return parse_blueprint_text(data)


def get_cube_grid(root: ET.Element) -> ET.Element:
    cube_grids = root.find("CubeGrids")
    if cube_grids is None:
        raise ValueError("blueprint does not contain CubeGrids")
    grids = [grid for grid in list(cube_grids) if local_name(grid.tag) == "CubeGrid"]
    if not grids:
        raise ValueError("blueprint does not contain CubeGrid")
    if len(grids) > 1:
        print(f"WARNING: blueprint has {len(grids)} CubeGrids; only the first grid is transformed")
    return grids[0]


def get_cube_blocks(grid: ET.Element) -> ET.Element:
    cube_blocks = grid.find("CubeBlocks")
    if cube_blocks is None:
        raise ValueError("CubeGrid does not contain CubeBlocks")
    return cube_blocks


def grid_step_from_blueprint(grid: ET.Element) -> float:
    size = (grid.findtext("GridSizeEnum") or "Large").strip().lower()
    if size == "small":
        return 0.5
    return 2.5


def strip_bloated_block_data(cube_blocks: ET.Element) -> int:
    removed = 0
    for block in list(cube_blocks):
        for child in list(block):
            if local_name(child.tag) not in ESSENTIAL_BLOCK_TAGS:
                block.remove(child)
                removed += 1
    return removed


def block_to_live(block: object, grid_step: float) -> Optional[LiveBlock]:
    local_position = getattr(block, "local_position", None)
    if not local_position or len(local_position) < 3:
        return None
    entity_id = getattr(block, "block_id", None)
    forward, up = live_block_orientation(block)
    local_position_m = _float_tuple3(local_position)
    return LiveBlock(
        block_type=str(getattr(block, "block_type", "") or ""),
        subtype=str(getattr(block, "subtype", "") or ""),
        entity_id=int(entity_id) if entity_id is not None else None,
        name=str(getattr(block, "name", "") or ""),
        min=Vec3i(
            int(round(float(local_position[0]) / grid_step)),
            int(round(float(local_position[1]) / grid_step)),
            int(round(float(local_position[2]) / grid_step)),
        ),
        orientation_forward=forward,
        orientation_up=up,
        local_position_m=local_position_m,
        world_position_m=read_float3_from_block(block, "world_pos", "worldPos", "world_position", "worldPosition"),
        relative_to_grid_center_m=read_float3_from_block(block, "relative_to_grid_center", "relativeToGridCenter"),
        world_axes=read_world_axes_from_block(block),
    )


def collect_live_blocks(grid: object, grid_step: float) -> list[LiveBlock]:
    result: list[LiveBlock] = []
    for block in getattr(grid, "iter_blocks")():
        live = block_to_live(block, grid_step)
        if live is not None:
            result.append(live)
    return result



def read_xml_orientation(element: ET.Element) -> tuple[Optional[Vec3i], Optional[Vec3i]]:
    orientation = element.find("BlockOrientation")
    if orientation is None:
        return None, None
    forward_name = orientation.attrib.get("Forward", "")
    up_name = orientation.attrib.get("Up", "")
    forward = DIRECTION_TO_VEC.get(forward_name)
    up = DIRECTION_TO_VEC.get(up_name)
    if forward is None or up is None:
        return None, None
    return Vec3i(*forward), Vec3i(*up)


def iter_cube_grids(root: ET.Element) -> list[ET.Element]:
    cube_grids = root.find("CubeGrids")
    if cube_grids is None:
        return []
    return [grid for grid in list(cube_grids) if local_name(grid.tag) == "CubeGrid"]


def collect_live_blocks_from_blueprint_xml(xml: str) -> list[LiveBlock]:
    """Read live block Min/BlockOrientation from a fresh grid blueprint export.

    Grid telemetry may expose local positions but omit BlockOrientation.  For a
    projector this is fatal: its local X/Y/Z UI axes can differ from grid X/Y/Z.
    A grid blueprint export is more authoritative because it serializes each
    block exactly as Space Engineers stores it.
    """
    tree = parse_blueprint_text(xml)
    root = tree.getroot()
    result: list[LiveBlock] = []
    for cube_grid in iter_cube_grids(root):
        cube_blocks = cube_grid.find("CubeBlocks")
        if cube_blocks is None:
            continue
        for element in list(cube_blocks):
            min_pos = read_min(element)
            if min_pos is None:
                continue
            forward, up = read_xml_orientation(element)
            result.append(
                LiveBlock(
                    block_type=xsi_type(element),
                    subtype=child_text(element, "SubtypeName"),
                    entity_id=parse_int(child_text(element, "EntityId")),
                    name=child_text(element, "CustomName"),
                    min=min_pos,
                    orientation_forward=forward,
                    orientation_up=up,
                )
            )
    return result


def try_refresh_live_frame_from_projector_export(
    projector: object,
    *,
    timeout: float,
    include_connected: bool,
    live_projector_id: Optional[int],
    telemetry_live_blocks: list[LiveBlock],
) -> tuple[list[LiveBlock], Optional[LiveBlock], str]:
    """Export the current live grid and use it as the coordinate/orientation frame.

    Returns (live_blocks, live_projector_block, message).  Falls back to the
    telemetry block list on any error.
    """
    telemetry_map = live_blocks_by_entity(telemetry_live_blocks)
    telemetry_projector = telemetry_map.get(live_projector_id) if live_projector_id is not None else None
    try:
        seq_id = projector.request_grid_blueprint(include_connected=include_connected)
        print(f"live frame export request_grid_blueprint sent: seq_id={seq_id}, include_connected={include_connected}")
        xml = wait_for_grid_blueprint_xml(projector, timeout)
        exported_blocks = collect_live_blocks_from_blueprint_xml(xml)
    except Exception as exc:
        return telemetry_live_blocks, telemetry_projector, f"live blueprint frame export failed: {exc}; using telemetry positions"

    exported_map = live_blocks_by_entity(exported_blocks)
    exported_projector = exported_map.get(live_projector_id) if live_projector_id is not None else None
    if exported_projector is None:
        return telemetry_live_blocks, telemetry_projector, (
            f"live blueprint frame export returned {len(exported_blocks)} blocks but did not contain projector "
            f"entity={live_projector_id}; using telemetry positions"
        )

    if not exported_blocks:
        return telemetry_live_blocks, telemetry_projector, "live blueprint frame export returned no blocks; using telemetry positions"

    # Prefer the exported frame as a coherent coordinate system.  Mixing
    # telemetry coordinates with exported projector orientation can introduce a
    # one-grid-cell drift if the origins differ.
    message = (
        f"live blueprint frame export accepted: blocks={len(exported_blocks)}, "
        f"projector Min={exported_projector.min}, orientation={orientation_to_text(exported_projector.orientation_forward, exported_projector.orientation_up)}"
    )
    if telemetry_projector is not None and telemetry_projector.min != exported_projector.min:
        message += f"; telemetry projector Min was {telemetry_projector.min}"
    return exported_blocks, exported_projector, message


def live_blocks_by_entity(live_blocks: Iterable[LiveBlock]) -> dict[int, LiveBlock]:
    result: dict[int, LiveBlock] = {}
    for block in live_blocks:
        if block.entity_id is not None:
            result[block.entity_id] = block
    return result


def fill_missing_min_from_live(cube_blocks: ET.Element, live_by_entity: dict[int, LiveBlock]) -> int:
    filled = 0
    if not live_by_entity:
        return filled
    for block in list(cube_blocks):
        if read_min(block) is not None:
            continue
        entity_id = parse_int(child_text(block, "EntityId"))
        if entity_id is None:
            continue
        live = live_by_entity.get(entity_id)
        if live is None:
            continue
        set_min(block, live.min)
        get_or_create_orientation(block)
        filled += 1
    return filled


def collect_missing_projector_min_elements(cube_blocks: ET.Element) -> set[int]:
    """Remember projector blocks whose Min was absent in the source XML.

    A projector exported without Min is not a real geometric cube anchor.  This
    happens with small projectors in projector-exported blueprints.  If we fill
    that Min from the live projector and then rotate it together with the ship,
    the resulting XML can be shifted in grid-origin projection mode.  Keeping
    this synthetic anchor fixed preserves both cases: projector-block anchoring
    still uses the same relative geometry, while grid-origin anchoring gets
    absolute contact cells equal to the calculated target.
    """
    result: set[int] = set()
    for block in list(cube_blocks):
        if read_min(block) is not None:
            continue
        if is_projector_type(xsi_type(block), child_text(block, "SubtypeName")):
            result.add(id(block))
    return result


def fill_missing_projector_min(cube_blocks: ET.Element, fallback_min: Optional[Vec3i]) -> int:
    if fallback_min is None:
        return 0
    filled = 0
    for block in list(cube_blocks):
        if read_min(block) is not None:
            continue
        if not is_projector_type(xsi_type(block), child_text(block, "SubtypeName")):
            continue
        set_min(block, fallback_min)
        get_or_create_orientation(block)
        ensure_projection_vector(block, "ProjectionOffset", Vec3i(0, 0, 0))
        ensure_projection_vector(block, "ProjectionRotation", Vec3i(0, 0, 0))
        filled += 1
    return filled




def first_preview_block_origin_min(cube_blocks: ET.Element) -> tuple[Vec3i, str]:
    """Return the Min that Space Engineers uses for PreviewGrids[0].CubeBlocks.First().

    MyProjectorClipboard recenters the preview so the first preview block is at the
    projector transform. If the first XML block has no <Min>, VRage deserializes the
    Vector3I as default (0,0,0). Filling that missing Min with the live projector
    cell changes the real vanilla origin and breaks small projector placement.
    """
    for block in list(cube_blocks):
        min_pos = read_min(block)
        subtype = child_text(block, "SubtypeName", "") or "?"
        entity_id = child_text(block, "EntityId", "?")
        if min_pos is None:
            return Vec3i(0, 0, 0), f"first XML block {xsi_type(block)}:{subtype} entity={entity_id} has no Min -> default (0,0,0)"
        return min_pos, f"first XML block {xsi_type(block)}:{subtype} entity={entity_id} Min={min_pos}"
    return Vec3i(0, 0, 0), "CubeBlocks is empty -> default (0,0,0)"

def remove_blocks_without_min(cube_blocks: ET.Element, *, preserve_projectors: bool = False) -> list[str]:
    removed: list[str] = []
    for block in list(cube_blocks):
        if read_min(block) is not None:
            continue
        if preserve_projectors and is_projector_type(xsi_type(block), child_text(block, "SubtypeName")):
            continue
        removed.append(f"{xsi_type(block)}:{child_text(block, 'SubtypeName', '') or '?'} entity={child_text(block, 'EntityId', '?')}")
        cube_blocks.remove(block)
    return removed


def collect_blueprint_blocks(cube_blocks: ET.Element) -> list[BlueprintBlock]:
    result: list[BlueprintBlock] = []
    for block in list(cube_blocks):
        min_pos = read_min(block)
        if min_pos is None:
            continue
        result.append(
            BlueprintBlock(
                element=block,
                block_type=xsi_type(block),
                subtype=child_text(block, "SubtypeName"),
                entity_id=parse_int(child_text(block, "EntityId")),
                name=child_text(block, "CustomName"),
                min=min_pos,
            )
        )
    return result


def refresh_blueprint_blocks_min(blocks: list[BlueprintBlock]) -> None:
    for block in blocks:
        new_min = read_min(block.element)
        if new_min is None:
            raise RuntimeError(f"block lost Min after transform: {block.block_type}:{block.subtype}")
        block.min = new_min


def filter_by_tag(items: Iterable[T], tag: str, text_getter: Callable[[T], str]) -> list[T]:
    if not tag:
        return list(items)
    needle = tag.lower()
    return [item for item in items if needle in text_getter(item).lower()]


def choose_blueprint_pair(blocks: list[BlueprintBlock], tag: str = "") -> ContactPair:
    merges = [block for block in blocks if is_merge_type(block.block_type, block.subtype)]
    connectors = [block for block in blocks if is_connector_type(block.block_type, block.subtype)]
    merges = filter_by_tag(merges, tag, lambda b: f"{b.name} {b.subtype} {b.block_type} {b.entity_id or ''}")
    connectors = filter_by_tag(connectors, tag, lambda b: f"{b.name} {b.subtype} {b.block_type} {b.entity_id or ''}")
    if not merges:
        raise ValueError("blueprint does not contain a Merge Block contact candidate")
    if not connectors:
        raise ValueError("blueprint does not contain a Connector contact candidate")

    pairs: list[tuple[int, ContactPair]] = []
    for merge in merges:
        for connector in connectors:
            distance = (connector.min - merge.min).manhattan()
            if distance == 0:
                continue
            pairs.append((distance, ContactPair(merge=merge, connector=connector)))
    if not pairs:
        raise ValueError("blueprint Merge Block and Connector candidates cannot form a contact pair")
    pairs.sort(key=lambda item: item[0])
    return pairs[0][1]


def choose_live_pair(
    live_blocks: list[LiveBlock],
    blueprint_pair: ContactPair,
    live_by_entity_map: dict[int, LiveBlock],
    tag: str = "",
) -> Optional[LiveContactPair]:
    if blueprint_pair.merge.entity_id is not None and blueprint_pair.connector.entity_id is not None:
        live_merge = live_by_entity_map.get(blueprint_pair.merge.entity_id)
        live_connector = live_by_entity_map.get(blueprint_pair.connector.entity_id)
        if live_merge is not None and live_connector is not None:
            return LiveContactPair(merge=live_merge, connector=live_connector)

    merges = [block for block in live_blocks if is_merge_type(block.block_type, block.subtype)]
    connectors = [block for block in live_blocks if is_connector_type(block.block_type, block.subtype)]
    merges = filter_by_tag(merges, tag, lambda b: f"{b.name} {b.subtype} {b.block_type} {b.entity_id or ''}")
    connectors = filter_by_tag(connectors, tag, lambda b: f"{b.name} {b.subtype} {b.block_type} {b.entity_id or ''}")
    if not merges or not connectors:
        return None

    pairs: list[tuple[int, LiveContactPair]] = []
    for merge in merges:
        for connector in connectors:
            distance = (connector.min - merge.min).manhattan()
            if distance == 0:
                continue
            pairs.append((distance, LiveContactPair(merge=merge, connector=connector)))
    if not pairs:
        return None
    pairs.sort(key=lambda item: item[0])
    return pairs[0][1]


def make_rotation(matrix: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]) -> Rotation:
    def rotate(v: Vec3i) -> Vec3i:
        return Vec3i(
            matrix[0][0] * v.x + matrix[0][1] * v.y + matrix[0][2] * v.z,
            matrix[1][0] * v.x + matrix[1][1] * v.y + matrix[1][2] * v.z,
            matrix[2][0] * v.x + matrix[2][1] * v.y + matrix[2][2] * v.z,
        )
    return rotate


def determinant(matrix: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]) -> int:
    a = matrix
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def cube_rotations() -> list[tuple[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]], Rotation]]:
    rotations = []
    for perm in permutations(range(3)):
        for signs in product((-1, 1), repeat=3):
            rows = []
            for row_index in range(3):
                row = [0, 0, 0]
                row[perm[row_index]] = signs[row_index]
                rows.append(tuple(row))
            matrix = (rows[0], rows[1], rows[2])
            if determinant(matrix) == 1:
                rotations.append((matrix, make_rotation(matrix)))
    rotations.sort(key=lambda item: 0 if item[0] == ((1, 0, 0), (0, 1, 0), (0, 0, 1)) else 1)
    return rotations


def choose_base_rotation(source_vector: Vec3i, target_vector: Vec3i) -> Rotation:
    if source_vector.manhattan() != target_vector.manhattan():
        raise ValueError(
            "blueprint contact pair and live contact pair have different grid distance: "
            f"blueprint={source_vector}, live={target_vector}"
        )
    for _matrix, rotation in cube_rotations():
        if rotation(source_vector) == target_vector:
            return rotation
    raise ValueError(f"cannot rotate blueprint contact vector {source_vector} to live contact vector {target_vector}")


def rotate_180_around_axis(axis: str, pivot: Vec3i) -> Rotation:
    if axis == "x":
        return lambda p: Vec3i(p.x, 2 * pivot.y - p.y, 2 * pivot.z - p.z)
    if axis == "y":
        return lambda p: Vec3i(2 * pivot.x - p.x, p.y, 2 * pivot.z - p.z)
    if axis == "z":
        return lambda p: Vec3i(2 * pivot.x - p.x, 2 * pivot.y - p.y, p.z)
    raise ValueError(f"unsupported contact axis: {axis}")


def rotate_180_direction_around_axis(axis: str) -> Rotation:
    if axis == "x":
        return lambda v: Vec3i(v.x, -v.y, -v.z)
    if axis == "y":
        return lambda v: Vec3i(-v.x, v.y, -v.z)
    if axis == "z":
        return lambda v: Vec3i(-v.x, -v.y, v.z)
    raise ValueError(f"unsupported contact axis: {axis}")


def compose_rotations(first: Rotation, second: Rotation) -> Rotation:
    return lambda value: second(first(value))


def rotate_steps_around_axis(axis: str, steps: int) -> Rotation:
    normalized = steps % 4

    def rotate_once_x(v: Vec3i) -> Vec3i:
        return Vec3i(v.x, -v.z, v.y)

    def rotate_once_y(v: Vec3i) -> Vec3i:
        return Vec3i(v.z, v.y, -v.x)

    def rotate_once_z(v: Vec3i) -> Vec3i:
        return Vec3i(-v.y, v.x, v.z)

    if axis == "x":
        rotate_once = rotate_once_x
    elif axis == "y":
        rotate_once = rotate_once_y
    elif axis == "z":
        rotate_once = rotate_once_z
    else:
        raise ValueError(f"unsupported rotation axis: {axis}")

    def rotate(value: Vec3i) -> Vec3i:
        result = value
        for _ in range(normalized):
            result = rotate_once(result)
        return result

    return rotate


def projection_rotation_for_contact_axis(axis: str, preflip: bool) -> Vec3i:
    if not preflip:
        return Vec3i(0, 0, 0)
    # ProjectionRotation uses source-code yaw/pitch/roll fields:
    # x=yaw around local Y, y=pitch around local X, z=roll around local Z.
    if axis == "x":
        return Vec3i(0, 2, 0)
    if axis == "y":
        return Vec3i(2, 0, 0)
    if axis == "z":
        return Vec3i(0, 0, 2)
    raise ValueError(f"unsupported contact axis: {axis}")


def projection_rotation_transform(rotation: Vec3i) -> Rotation:
    # Space Engineers does NOT interpret ProjectionRotation as simple
    # rotate-X / rotate-Y / rotate-Z UI fields.  Vanilla MyProjectorBase does:
    #
    #   Vector3 angles = ProjectionRotation * RotationAngleStepDeg;
    #   Quaternion.CreateFromYawPitchRoll(angles.X, angles.Y, angles.Z);
    #
    # Therefore:
    #   rotation.x is yaw   -> local Y axis
    #   rotation.y is pitch -> local X axis
    #   rotation.z is roll  -> local Z axis
    #
    # With Space Engineers/XNA row-vector matrix convention, yaw/pitch/roll is
    # applied as yaw, then pitch, then roll in projector-local coordinates.
    # For the common 180-degree flip around local X this yields (0, 2, 0),
    # not the old incorrect (0, 2, 2).
    yaw_y = rotate_steps_around_axis("y", rotation.x)
    pitch_x = rotate_steps_around_axis("x", rotation.y)
    roll_z = rotate_steps_around_axis("z", rotation.z)
    return compose_rotations(compose_rotations(yaw_y, pitch_x), roll_z)


def rotations_are_equal(first: Rotation, second: Rotation) -> bool:
    for basis in (Vec3i(1, 0, 0), Vec3i(0, 1, 0), Vec3i(0, 0, 1)):
        if first(basis) != second(basis):
            return False
    return True


def find_projection_rotation_for_transform(desired_transform: Rotation) -> Vec3i:
    for x in range(4):
        for y in range(4):
            for z in range(4):
                candidate = Vec3i(x, y, z)
                if rotations_are_equal(projection_rotation_transform(candidate), desired_transform):
                    return candidate
    raise ValueError("cannot represent prepared blueprint rotation with projector ProjectionRotation steps")


def find_projection_rotation_matching_pairs(pairs: list[tuple[Vec3i, Vec3i]]) -> Optional[Vec3i]:
    """Find a native ProjectionRotation matching all source->target direction pairs.

    ProjectionRotation uses the Space Engineers yaw/pitch/roll convention, so
    this enumerates actual projector rotations instead of assuming X/Y/Z UI
    fields are direct axes.  Pairs are expressed in projector-local cells.
    """
    for x in range(4):
        for y in range(4):
            for z in range(4):
                candidate = Vec3i(x, y, z)
                transform = projection_rotation_transform(candidate)
                if all(transform(source) == target for source, target in pairs):
                    return candidate
    return None


def choose_merge_mate_face_for_contact(
    blueprint_merge: BlueprintBlock,
    rotation_transform: Rotation,
    projector_to_grid: Rotation,
    contact_normal: Optional[Vec3i],
    requested_face: str,
) -> str:
    """Resolve the merge mating face after the contact side is known.

    For small-grid projector alignment the important rule is face-to-face:
    the projected merge face must point back toward the live merge block, i.e.
    projected_face == -contact_normal.  If the user did not force a face,
    select the model face that satisfies that rule.
    """
    if requested_face != "auto":
        return requested_face
    if contact_normal is None or contact_normal.manhattan() != 1:
        return "forward"
    wanted = -contact_normal
    for face_name in MERGE_MATE_FACE_CHOICES:
        projected_face = projector_to_grid(rotation_transform(block_model_face_vector(blueprint_merge, face_name)))
        if projected_face == wanted:
            return face_name
    return "forward"


def prepared_projection_direction_transform(source_vector: Vec3i, target_vector: Vec3i, *, preflip: bool) -> Rotation:
    base_rotation = choose_base_rotation(source_vector, target_vector)
    if not preflip:
        return base_rotation
    contact_axis = target_vector.axis_name()
    if contact_axis is None:
        raise ValueError(f"prepared contact pair must be axis-aligned, got vector {target_vector}")
    return compose_rotations(base_rotation, rotate_180_direction_around_axis(contact_axis))


def describe_rotation_on_basis(rotation: Rotation) -> str:
    return f"X->{rotation(Vec3i(1, 0, 0))}, Y->{rotation(Vec3i(0, 1, 0))}, Z->{rotation(Vec3i(0, 0, 1))}"


def prepare_blueprint_geometry(
    blocks: list[BlueprintBlock],
    blueprint_pair: ContactPair,
    live_pair: LiveContactPair,
    *,
    preflip: bool,
    fixed_projector_element_ids: Optional[set[int]] = None,
    target_contact_vector: Optional[Vec3i] = None,
) -> tuple[str, bool]:
    prepared_target_vector = target_contact_vector or live_pair.vector
    base_rotation = choose_base_rotation(blueprint_pair.vector, prepared_target_vector)
    contact_axis = prepared_target_vector.axis_name()
    if contact_axis is None:
        raise ValueError(f"prepared contact pair must be axis-aligned, got vector {prepared_target_vector}")

    pivot = blueprint_pair.merge.min
    direction_transform: Rotation = base_rotation

    def position_transform(position: Vec3i) -> Vec3i:
        return pivot + base_rotation(position - pivot)

    if preflip:
        line_rotation = rotate_180_around_axis(contact_axis, pivot)
        line_direction_rotation = rotate_180_direction_around_axis(contact_axis)
        old_position_transform = position_transform
        position_transform = lambda position: line_rotation(old_position_transform(position))
        direction_transform = compose_rotations(direction_transform, line_direction_rotation)

    fixed_projector_element_ids = fixed_projector_element_ids or set()
    for block in blocks:
        if id(block.element) in fixed_projector_element_ids:
            # This projector Min was synthesized from the live projector position.
            # Keep it as a fixed anchor instead of rotating it as if it had been a
            # normal blueprint block.  The projected ship is moved relative to it
            # later by shift_blueprint_blocks(..., skip_anchor_projector=...).
            get_or_create_orientation(block.element)
            ensure_projection_vector(block.element, "ProjectionOffset", Vec3i(0, 0, 0))
            ensure_projection_vector(block.element, "ProjectionRotation", Vec3i(0, 0, 0))
            continue

        # Min in Space Engineers is the minimum corner of the occupied cell box.
        # Rotating only that single Min cell is wrong for thrusters/tanks/cargo and
        # causes visible drift/overlap. Rotate the whole occupied box, then write
        # the new minimum corner.
        new_min = transform_block_min_by_occupied_cells(block, position_transform)
        set_min(block.element, new_min)
        block.min = new_min
        update_orientation(block.element, direction_transform)
        if is_projector_type(block.block_type, block.subtype):
            ensure_projection_vector(block.element, "ProjectionOffset", Vec3i(0, 0, 0))
            ensure_projection_vector(block.element, "ProjectionRotation", Vec3i(0, 0, 0))

    transformed_merge = blueprint_pair.merge.min
    transformed_connector = blueprint_pair.connector.min
    expected_connector = transformed_merge + prepared_target_vector
    if transformed_connector != expected_connector:
        raise RuntimeError(
            "internal transform error: blueprint contact vector was not prepared correctly; "
            f"connector={transformed_connector}, expected={expected_connector}"
        )

    return contact_axis, preflip


def parse_vec3i_text(value: str) -> Vec3i:
    parts = [part.strip() for part in value.replace(";", ",").replace(" ", ",").split(",") if part.strip()]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("value must have three integers, for example 0,1,-6")
    try:
        return Vec3i(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must have three integers") from exc


def find_projector(grid: object, name_filter: str = "", subtype_filter: str = "") -> object:
    projectors = list(getattr(grid, "find_devices_by_type")("projector"))
    if name_filter:
        needle = name_filter.lower()
        projectors = [projector for projector in projectors if needle in str(projector.name or "").lower()]
    if subtype_filter:
        needle = subtype_filter.lower()
        projectors = [projector for projector in projectors if needle in _projector_subtype(projector).lower()]
    if not projectors:
        suffix_parts = []
        if name_filter:
            suffix_parts.append(f" with name containing '{name_filter}'")
        if subtype_filter:
            suffix_parts.append(f" with subtype containing '{subtype_filter}'")
        suffix = "".join(suffix_parts)
        raise RuntimeError(f"projector{suffix} not found on grid {getattr(grid, 'name', '?')}")
    return projectors[0]


def _projector_subtype(projector: object) -> str:
    """Read projector block subtype from metadata, telemetry snapshot, or block attribute.

    Subgrid devices often arrive with an empty ``metadata.extra`` and no
    ``device.name`` set, so we have to fall back to the latest telemetry
    snapshot, which always carries the canonical ``subtype`` field.
    """
    meta = getattr(projector, "metadata", None)
    if meta is not None:
        extra = getattr(meta, "extra", None) or {}
        sub = extra.get("subtype") or extra.get("SubtypeName")
        if sub:
            return str(sub)
    telemetry_key = getattr(projector, "telemetry_key", None)
    if telemetry_key:
        redis = getattr(projector, "redis", None)
        get_json = getattr(redis, "get_json", None)
        if callable(get_json):
            try:
                snapshot = get_json(telemetry_key)
            except Exception:
                snapshot = None
            if isinstance(snapshot, dict):
                sub = snapshot.get("subtype") or snapshot.get("SubtypeName")
                if sub:
                    return str(sub)
    block = getattr(projector, "block", None)
    if block is not None:
        sub = getattr(block, "subtype", None)
        if sub:
            return str(sub)
    return ""




def default_projector_ui_origin_correction(projector: object, subtype_filter: str = "") -> Vec3i:
    """Return UI ProjectionOffset correction for projector model origin quirks.

    Small vanilla projectors report their block Min correctly, but the visible
    projection origin is shifted from that cube anchor by one UI step on local
    X and Y.  A manual projector panel offset of X=-1, Y=-1, Z=0 compensates
    this origin shift.  Large projectors do not need this correction.
    """
    text = f"{subtype_filter} {_projector_subtype(projector)}".lower()
    if "smallprojector" in text:
        return Vec3i(-1, -1, 0)
    return Vec3i(0, 0, 0)


def resolve_projector_ui_origin_correction(projector: Optional[object], subtype_filter: str, explicit: Optional[Vec3i], disabled: bool) -> Vec3i:
    if explicit is not None:
        return explicit
    if disabled or projector is None:
        return Vec3i(0, 0, 0)
    return default_projector_ui_origin_correction(projector, subtype_filter)


def add_vec3i(a: Vec3i, b: Vec3i) -> Vec3i:
    return Vec3i(a.x + b.x, a.y + b.y, a.z + b.z)

def projector_device_id(projector: object) -> Optional[int]:
    metadata = getattr(projector, "metadata", None)
    device_id = getattr(metadata, "device_id", None)
    return parse_int(device_id)


def make_synthetic_projector_anchor(value: Vec3i, reason: str) -> BlueprintBlock:
    synthetic = ET.Element("MyObjectBuilder_Projector")
    set_min(synthetic, value)
    return BlueprintBlock(
        element=synthetic,
        block_type="MyObjectBuilder_Projector",
        subtype="SyntheticProjectorAnchor",
        entity_id=None,
        name=reason,
        min=value,
    )


def choose_blueprint_projector_block(
    blocks: list[BlueprintBlock],
    live_projector_id: Optional[int],
    explicit_min: Optional[Vec3i],
    live_projector_min: Optional[Vec3i],
    blueprint_pair: ContactPair,
) -> BlueprintBlock:
    if explicit_min is not None:
        return make_synthetic_projector_anchor(explicit_min, "manual blueprint projector anchor")

    projectors = [block for block in blocks if is_projector_type(block.block_type, block.subtype)]
    if live_projector_id is not None:
        for block in projectors:
            if block.entity_id == live_projector_id:
                return block

    if projectors:
        if len(projectors) > 1:
            print("WARNING: several projector blocks found in blueprint; using the first one with Min")
        return projectors[0]

    if live_projector_min is not None:
        print(
            "WARNING: blueprint projector block has no usable Min; "
            "using live projector Min as a synthetic same-ship anchor. "
            "This is correct for cloning from a blueprint of the current ship."
        )
        return make_synthetic_projector_anchor(live_projector_min, "live projector Min fallback")

    print(
        "WARNING: blueprint projector block has no usable Min and live projector is unavailable; "
        "using merge contact as a weak offline anchor."
    )
    return make_synthetic_projector_anchor(blueprint_pair.merge.min, "offline merge fallback")


def live_projector_block_from_device(
    projector: object,
    live_by_entity_map: dict[int, LiveBlock],
    grid_step: float,
) -> LiveBlock:
    device_id = projector_device_id(projector)
    if device_id is not None:
        live = live_by_entity_map.get(device_id)
        if live is not None:
            return live

    block = getattr(projector, "block", None)
    live = block_to_live(block, grid_step) if block is not None else None
    if live is not None:
        return live

    raise RuntimeError("cannot resolve live projector block position from telemetry")


def axis_vec(axis: str, sign: int) -> Vec3i:
    if axis == "x":
        return Vec3i(sign, 0, 0)
    if axis == "y":
        return Vec3i(0, sign, 0)
    if axis == "z":
        return Vec3i(0, 0, sign)
    raise ValueError(f"invalid axis: {axis}")


def normal_candidates(contact_vector: Vec3i, normal_text: str) -> list[Vec3i]:
    if normal_text != "auto":
        axis, sign = UNIT_AXES[normal_text]
        normal = axis_vec(axis, sign)
        if contact_vector.dot(normal) != 0:
            raise ValueError(f"normal {normal} must be perpendicular to contact vector {contact_vector}")
        return [normal]

    candidates: list[Vec3i] = []
    for axis in ("x", "y", "z"):
        for sign in (-1, 1):
            normal = axis_vec(axis, sign)
            if contact_vector.dot(normal) == 0:
                candidates.append(normal)
    return candidates


def predicted_position(
    live_projector_min: Vec3i,
    blueprint_projector_min: Vec3i,
    block_min: Vec3i,
    offset: Vec3i,
    anchor_mode: str = "grid-origin",
    projector_to_grid: Rotation = identity_rotation,
) -> Vec3i:
    if anchor_mode == "projector-block":
        return live_projector_min + projector_to_grid((block_min - blueprint_projector_min) + offset)
    if anchor_mode == "projector-origin":
        return live_projector_min + projector_to_grid(block_min + offset)
    return block_min + offset


def compute_offset_for_target(
    live_projector_min: Vec3i,
    blueprint_projector_min: Vec3i,
    blueprint_contact_min: Vec3i,
    target_contact_min: Vec3i,
    anchor_mode: str = "grid-origin",
    grid_to_projector: Rotation = identity_rotation,
) -> Vec3i:
    if anchor_mode == "projector-block":
        current_local = blueprint_contact_min - blueprint_projector_min
        target_local = grid_to_projector(target_contact_min - live_projector_min)
        return target_local - current_local
    if anchor_mode == "projector-origin":
        current_local = blueprint_contact_min
        target_local = grid_to_projector(target_contact_min - live_projector_min)
        return target_local - current_local
    return target_contact_min - blueprint_contact_min


def choose_placement(
    blocks: list[BlueprintBlock],
    live_blocks: list[LiveBlock],
    blueprint_pair: ContactPair,
    live_pair: LiveContactPair,
    blueprint_projector_min: Vec3i,
    live_projector_min: Vec3i,
    *,
    contact_mode: str,
    contact_gap: int,
    normal_text: str,
    anchor_mode: str = "grid-origin",
    projector_to_grid: Rotation = identity_rotation,
    grid_to_projector: Rotation = identity_rotation,
    preferred_normal: Optional[Vec3i] = None,
) -> PlacementCandidate:
    if contact_gap < 0:
        raise ValueError("contact gap must be >= 0")

    live_occupied = {block.min for block in live_blocks}
    live_center = Vec3i(
        round(sum(block.min.x for block in live_blocks) / max(1, len(live_blocks))),
        round(sum(block.min.y for block in live_blocks) / max(1, len(live_blocks))),
        round(sum(block.min.z for block in live_blocks) / max(1, len(live_blocks))),
    )

    if contact_mode == "overlay":
        normals = [Vec3i(0, 0, 0)]
    else:
        normals = resolve_auto_contact_normals(live_pair.vector, normal_text, preferred_normal)

    candidates: list[PlacementCandidate] = []
    for normal in normals:
        shift = normal * contact_gap
        target_merge = live_pair.merge.min + shift
        target_connector = live_pair.connector.min + shift
        offset = compute_offset_for_target(
            live_projector_min,
            blueprint_projector_min,
            blueprint_pair.merge.min,
            target_merge,
            anchor_mode,
            grid_to_projector,
        )

        predicted_connector = predicted_position(
            live_projector_min,
            blueprint_projector_min,
            blueprint_pair.connector.min,
            offset,
            anchor_mode,
            projector_to_grid,
        )
        if predicted_connector != target_connector:
            raise RuntimeError(
                "internal offset error: connector does not match target; "
                f"predicted={predicted_connector}, target={target_connector}"
            )

        predicted_positions = [
            predicted_position(live_projector_min, blueprint_projector_min, block.min, offset, anchor_mode, projector_to_grid)
            for block in blocks
        ]
        collisions = sum(1 for position in predicted_positions if position in live_occupied)
        center = Vec3i(
            round(sum(position.x for position in predicted_positions) / max(1, len(predicted_positions))),
            round(sum(position.y for position in predicted_positions) / max(1, len(predicted_positions))),
            round(sum(position.z for position in predicted_positions) / max(1, len(predicted_positions))),
        )
        center_score = (center - live_center).manhattan()
        candidates.append(
            PlacementCandidate(
                normal=normal,
                target_merge=target_merge,
                target_connector=target_connector,
                offset=offset,
                collisions=collisions,
                predicted_center_score=center_score,
            )
        )

    if not candidates:
        raise RuntimeError("no placement candidates were generated")

    candidates.sort(key=lambda item: (item.collisions, -item.predicted_center_score, item.normal.as_tuple()))
    return candidates[0]


def inverse_rotation(rotation: Rotation) -> Rotation:
    """Return the inverse of a cube-grid rotation function.

    Space Engineers applies projector UI offset in projector-local blueprint
    coordinates first, then applies ProjectionRotation to the shifted blueprint.
    To compute such an offset from a desired grid-space contact point we need
    the inverse of the requested native ProjectionRotation.
    """
    basis = (Vec3i(1, 0, 0), Vec3i(0, 1, 0), Vec3i(0, 0, 1))
    for _matrix, candidate in cube_rotations():
        if all(candidate(rotation(axis)) == axis for axis in basis):
            return candidate
    raise ValueError("cannot invert projector rotation transform")


def predicted_position_with_rotation(
    live_projector_min: Vec3i,
    blueprint_projector_min: Vec3i,
    block_min: Vec3i,
    offset: Vec3i,
    rotation_transform: Rotation,
    anchor_mode: str = "grid-origin",
    projector_to_grid: Rotation = identity_rotation,
) -> Vec3i:
    # Space Engineers source formula from MyProjectorClipboard.UpdateGridTransformations():
    #   worldMatrix = ProjectionRotation * projector.WorldMatrix
    #   worldMatrix.Translation -= Transform(ProjectionOffset * GridSize, projector.WorldMatrix.GetOrientation())
    #   worldMatrix.Translation += worldMatrix.Translation - GridIntegerToWorld(firstBlock.Position, worldMatrix)
    # Therefore the effective block position is:
    #   projector + R(block - firstBlock) - projectorOrientation(offset)
    # Offset is NOT rotated by ProjectionRotation.  It is subtracted in projector-local axes.
    if anchor_mode == "projector-block":
        rotated_rel = rotation_transform(block_min - blueprint_projector_min)
        return live_projector_min + projector_to_grid(rotated_rel - offset)
    if anchor_mode == "projector-origin":
        rotated_rel = rotation_transform(block_min)
        return live_projector_min + projector_to_grid(rotated_rel - offset)
    return rotation_transform(block_min) - offset


def compute_offset_for_target_with_rotation(
    live_projector_min: Vec3i,
    blueprint_projector_min: Vec3i,
    blueprint_contact_min: Vec3i,
    target_contact_min: Vec3i,
    rotation_transform: Rotation,
    anchor_mode: str = "grid-origin",
    grid_to_projector: Rotation = identity_rotation,
) -> Vec3i:
    # In the vanilla projector formula offset is subtracted after rotating the blueprint,
    # and offset itself is expressed in projector-local axes.  Solve:
    #   targetLocal = R(contact - anchor) - offset
    #   offset = R(contact - anchor) - targetLocal
    if anchor_mode == "projector-block":
        target_local = grid_to_projector(target_contact_min - live_projector_min)
        rotated_contact_rel = rotation_transform(blueprint_contact_min - blueprint_projector_min)
        return rotated_contact_rel - target_local
    if anchor_mode == "projector-origin":
        target_local = grid_to_projector(target_contact_min - live_projector_min)
        rotated_contact_rel = rotation_transform(blueprint_contact_min)
        return rotated_contact_rel - target_local
    return rotation_transform(blueprint_contact_min) - target_contact_min


def choose_placement_projector_rotation(
    blocks: list[BlueprintBlock],
    live_blocks: list[LiveBlock],
    blueprint_pair: ContactPair,
    live_pair: LiveContactPair,
    blueprint_projector_min: Vec3i,
    live_projector_min: Vec3i,
    projection_rotation: Vec3i,
    *,
    contact_mode: str,
    contact_gap: int,
    normal_text: str,
    anchor_mode: str = "grid-origin",
    projector_to_grid: Rotation = identity_rotation,
    grid_to_projector: Rotation = identity_rotation,
    preferred_normal: Optional[Vec3i] = None,
) -> PlacementCandidate:
    if contact_gap < 0:
        raise ValueError("contact gap must be >= 0")

    rotation_transform = projection_rotation_transform(projection_rotation)
    rotated_pair_vector = rotation_transform(blueprint_pair.vector)
    expected_pair_vector = grid_to_projector(live_pair.vector)
    if rotated_pair_vector != expected_pair_vector:
        raise ValueError(
            "projector rotation does not keep the blueprint contact pair aligned with the live pair: "
            f"rotated={rotated_pair_vector}, expected-projector-local={expected_pair_vector}, live-grid={live_pair.vector}. "
            "Use --rotation-mode xml only as a legacy fallback."
        )

    live_occupied = {block.min for block in live_blocks}
    live_center = Vec3i(
        round(sum(block.min.x for block in live_blocks) / max(1, len(live_blocks))),
        round(sum(block.min.y for block in live_blocks) / max(1, len(live_blocks))),
        round(sum(block.min.z for block in live_blocks) / max(1, len(live_blocks))),
    )

    if contact_mode == "overlay":
        normals = [Vec3i(0, 0, 0)]
    else:
        normals = resolve_auto_contact_normals(live_pair.vector, normal_text, preferred_normal)

    candidates: list[PlacementCandidate] = []
    for normal in normals:
        shift = normal * contact_gap
        target_merge = live_pair.merge.min + shift
        target_connector = live_pair.connector.min + shift
        offset = compute_offset_for_target_with_rotation(
            live_projector_min,
            blueprint_projector_min,
            blueprint_pair.merge.min,
            target_merge,
            rotation_transform,
            anchor_mode,
            grid_to_projector,
        )

        predicted_connector = predicted_position_with_rotation(
            live_projector_min,
            blueprint_projector_min,
            blueprint_pair.connector.min,
            offset,
            rotation_transform,
            anchor_mode,
            projector_to_grid,
        )
        if predicted_connector != target_connector:
            raise RuntimeError(
                "internal projector offset error: connector does not match target; "
                f"predicted={predicted_connector}, target={target_connector}"
            )

        predicted_positions = [
            predicted_position_with_rotation(live_projector_min, blueprint_projector_min, block.min, offset, rotation_transform, anchor_mode, projector_to_grid)
            for block in blocks
        ]
        collisions = sum(1 for position in predicted_positions if position in live_occupied)
        center = Vec3i(
            round(sum(position.x for position in predicted_positions) / max(1, len(predicted_positions))),
            round(sum(position.y for position in predicted_positions) / max(1, len(predicted_positions))),
            round(sum(position.z for position in predicted_positions) / max(1, len(predicted_positions))),
        )
        center_score = (center - live_center).manhattan()
        candidates.append(
            PlacementCandidate(
                normal=normal,
                target_merge=target_merge,
                target_connector=target_connector,
                offset=offset,
                collisions=collisions,
                predicted_center_score=center_score,
            )
        )

    if not candidates:
        raise RuntimeError("no placement candidates were generated")

    candidates.sort(key=lambda item: (item.collisions, -item.predicted_center_score, item.normal.as_tuple()))
    return candidates[0]



def contact_alignment_report(
    *,
    final_merge: Vec3i,
    final_connector: Vec3i,
    projected_merge_face: Optional[Vec3i],
    live_pair: LiveContactPair,
    placement: PlacementCandidate,
    contact_gap: int,
) -> bool:
    """Print a strict contact check for the projected Merge/Connector pair.

    The important distinction is that the projected blocks should not overlap the
    live blocks.  In normal opposite mode they must be exactly one contact-gap
    away from the live pair, and both projected blocks must have the same delta
    from their corresponding live blocks.
    """
    merge_delta_to_target = final_merge - placement.target_merge
    connector_delta_to_target = final_connector - placement.target_connector
    merge_delta_to_live = final_merge - live_pair.merge.min
    connector_delta_to_live = final_connector - live_pair.connector.min
    expected_live_delta = placement.normal * contact_gap
    pair_vector = final_connector - final_merge

    merge_target_ok = merge_delta_to_target == Vec3i(0, 0, 0)
    connector_target_ok = connector_delta_to_target == Vec3i(0, 0, 0)
    merge_live_ok = merge_delta_to_live == expected_live_delta
    connector_live_ok = connector_delta_to_live == expected_live_delta
    pair_ok = pair_vector == live_pair.vector
    expected_projected_face = -expected_live_delta if expected_live_delta != Vec3i(0, 0, 0) else None
    face_ok = True
    if projected_merge_face is not None and expected_projected_face is not None:
        face_ok = projected_merge_face == expected_projected_face
    all_ok = merge_target_ok and connector_target_ok and merge_live_ok and connector_live_ok and pair_ok and face_ok

    print("Contact verification:")
    print(f"  live merge Min:             {live_pair.merge.min}")
    print(f"  live connector Min:         {live_pair.connector.min}")
    print(f"  projected merge Min:        {final_merge}")
    print(f"  projected connector Min:    {final_connector}")
    print(f"  expected projected merge:   {placement.target_merge}")
    print(f"  expected projected connector:{placement.target_connector}")
    print(f"  merge target delta:         {merge_delta_to_target} {'OK' if merge_target_ok else 'FAIL'}")
    print(f"  connector target delta:     {connector_delta_to_target} {'OK' if connector_target_ok else 'FAIL'}")
    print(f"  expected live contact delta:{expected_live_delta}")
    print(f"  merge-live delta:           {merge_delta_to_live} {'OK' if merge_live_ok else 'FAIL'}")
    print(f"  connector-live delta:       {connector_delta_to_live} {'OK' if connector_live_ok else 'FAIL'}")
    print(f"  projected pair vector:      {pair_vector}; live pair vector: {live_pair.vector} {'OK' if pair_ok else 'FAIL'}")
    if projected_merge_face is None or expected_projected_face is None:
        print("  projected merge face:      ? (face verification unavailable)")
    else:
        print(f"  projected merge face:       {projected_merge_face}; expected: {expected_projected_face} {'OK' if face_ok else 'FAIL'}")
    print(f"  CONTACT VERIFY:             {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def _dict_int_value(data: dict, names: tuple[str, ...]) -> Optional[int]:
    for name in names:
        parsed = parse_int(data.get(name))
        if parsed is not None:
            return parsed
    return None


def _extract_named_vec3(data: dict, names: tuple[str, ...]) -> Optional[Vec3i]:
    for name in names:
        value = data.get(name)
        parsed = telemetry_vec3(value)
        if parsed is not None:
            return parsed
        if isinstance(value, dict):
            parsed = telemetry_vec3(value.get("min") or value.get("Min") or value.get("position") or value.get("Position"))
            if parsed is not None:
                return parsed
    return None


def _walk_dicts(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _projection_report_entries_for_entity(report: dict, entity_id: Optional[int]) -> list[dict]:
    if entity_id is None:
        return []
    result: list[dict] = []
    id_keys = (
        "entityId",
        "EntityId",
        "id",
        "Id",
        "blockId",
        "BlockId",
        "sourceEntityId",
        "originalEntityId",
        "projectedEntityId",
    )
    for item in _walk_dicts(report):
        if _dict_int_value(item, id_keys) == entity_id:
            result.append(item)
    return result


def _summarize_projection_report_entry(entry: dict) -> str:
    position = _extract_named_vec3(entry, ("min", "Min", "position", "Position", "localPosition", "local_pos", "projectedMin", "projectedPosition"))
    status_parts: list[str] = []
    for key in ("status", "state", "reason", "buildable", "isBuildable", "missing", "remaining", "definition", "subtype", "SubtypeName"):
        if key in entry:
            status_parts.append(f"{key}={entry.get(key)}")
    position_text = f"pos={position}" if position is not None else "pos=?"
    details = ", ".join(status_parts[:8]) if status_parts else "no status fields"
    return f"{position_text}; {details}"


def scan_projection_contact_report(
    projector: object,
    *,
    wait: float,
    max_blocks: int,
    merge_entity_id: Optional[int],
    connector_entity_id: Optional[int],
    output_path: Optional[Path] = None,
) -> None:
    """Ask the plugin for a projection report and try to locate contact blocks.

    This is the only check that can use the projector plugin's view after the
    blueprint has been loaded.  Some plugin builds only report missing blocks and
    component counts, so absence of contact EntityId entries is diagnostic rather
    than a hard failure.
    """
    report: dict = {}

    # New plugin path: asks the C# projector device to return actual projected-grid
    # data, not only Python-calculated coordinates. Older plugin builds will simply
    # ignore this command; then we fall back to the old projection_report wrapper.
    sender = getattr(projector, "send_command", None)
    if callable(sender):
        try:
            seq_id = sender({
                "cmd": "projection_contact_report",
                "state": {
                    "sourceMergeEntityId": int(merge_entity_id) if merge_entity_id is not None else None,
                    "sourceConnectorEntityId": int(connector_entity_id) if connector_entity_id is not None else None,
                    "contact": True,
                    "includeProjectedBlocks": True,
                    "maxBlocks": int(max_blocks),
                },
            })
            print(f"projection_contact_report request sent: seq_id={seq_id}")
            time.sleep(max(0.0, wait))
            refresh_projector_telemetry(projector, timeout=1.0)
        except Exception as exc:
            print(f"WARNING: projection_contact_report request failed: {exc}")

    getter = getattr(projector, "projection_report", None)
    if callable(getter):
        try:
            report = getter()
        except Exception:
            report = {}

    if not isinstance(report, dict) or not report:
        scanner = getattr(projector, "scan_projection_report", None)
        if callable(scanner):
            try:
                report = scanner(wait=wait, max_blocks=max_blocks)
            except Exception as exc:
                print(f"WARNING: projection report scan failed: {exc}")
                report = {}
        else:
            requester = getattr(projector, "request_projection_report", None)
            if callable(requester):
                try:
                    seq_id = requester(max_blocks=max_blocks)
                    print(f"projection_report request sent: seq_id={seq_id}")
                    time.sleep(max(0.0, wait))
                    refresh_projector_telemetry(projector, timeout=1.0)
                except Exception as exc:
                    print(f"WARNING: projection report request failed: {exc}")
            getter = getattr(projector, "projection_report", None)
            if callable(getter):
                try:
                    report = getter()
                except Exception:
                    report = {}

    if not isinstance(report, dict) or not report:
        print("Projection contact report: unavailable or empty")
        return

    if output_path is not None:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Projection contact report saved: {output_path}")
        except Exception as exc:
            print(f"WARNING: failed to save projection report: {exc}")

    print(f"Projection contact report keys: {', '.join(sorted(str(key) for key in report.keys())[:20])}")
    source = report.get("source")
    if source:
        print(f"Projection contact report source: {source}")
    actual = report.get("actualProjected")
    if isinstance(actual, dict):
        print(
            "Projection actual projected grids: "
            f"available={actual.get('available')} gridCount={actual.get('gridCount')} reason={actual.get('reason', '')}"
        )
        grids = actual.get("grids")
        if isinstance(grids, list):
            for grid_index, grid_data in enumerate(grids[:3], 1):
                if not isinstance(grid_data, dict):
                    continue
                print(
                    f"  actual grid[{grid_index}]: id={grid_data.get('gridId')} "
                    f"name={grid_data.get('gridName')} blockCount={grid_data.get('blockCount')} "
                    f"listed={grid_data.get('listedBlockCount')}"
                )
                blocks = grid_data.get("blocks")
                if isinstance(blocks, list):
                    shown = 0
                    for block in blocks:
                        if not isinstance(block, dict):
                            continue
                        text = f"{block.get('type')}/{block.get('subtype')}".lower()
                        if block.get("selectedContact") or "merge" in text or "connector" in text:
                            print(f"    actual block: {_summarize_projection_report_entry(block)} entity={block.get('entityId')}")
                            shown += 1
                        if shown >= 10:
                            break
    members = report.get("projectorReflectionMembers")
    if isinstance(members, list) and members:
        print("Projection projector reflection members with projection/grid names:")
        for member in members[:30]:
            if isinstance(member, dict):
                print(
                    f"  {member.get('kind')} {member.get('name')} type={member.get('type')} "
                    f"valueType={member.get('valueType')} isNull={member.get('isNull')}"
                )
    for label, entity_id in (("merge", merge_entity_id), ("connector", connector_entity_id)):
        entries = _projection_report_entries_for_entity(report, entity_id)
        if not entries:
            print(f"Projection contact report: {label} entity={entity_id or '?'} not found")
            continue
        print(f"Projection contact report: {label} entity={entity_id} entries={len(entries)}")
        for index, entry in enumerate(entries[:5], 1):
            print(f"  {label}[{index}]: {_summarize_projection_report_entry(entry)}")



def build_projection_probe_candidates(
    *,
    live_projector_min: Vec3i,
    blueprint_projector_min: Vec3i,
    blueprint_pair: ContactPair,
    live_pair: LiveContactPair,
    base_offset: Vec3i,
    base_rotation: Vec3i,
    base_normal: Vec3i,
    anchor_mode: str,
    contact_gap: int,
    projector_to_grid: Rotation,
    grid_to_projector: Rotation,
    radius: int,
    rotation_mode: str,
    normal_mode: str,
    limit: int,
) -> list[dict]:
    """Build projector transform candidates for C# game-side probing.

    The Python math has repeatedly been wrong because the game applies projector
    transforms through internal code.  This list deliberately includes nearby
    offsets, contact-side alternatives and all rotations that preserve the
    merge/connector vector.  The plugin then tests them in the live game and
    ranks by BuildableBlocksCount.
    """
    radius = max(0, int(radius))
    limit = max(1, int(limit))

    if rotation_mode == "current":
        rotations = [base_rotation]
    else:
        rotations = []
        for x in range(4):
            for y in range(4):
                for z in range(4):
                    candidate = Vec3i(x, y, z)
                    if rotation_mode == "contact":
                        transformed_pair = projector_to_grid(projection_rotation_transform(candidate)(blueprint_pair.vector))
                        if transformed_pair != live_pair.vector:
                            continue
                    rotations.append(candidate)
        if not rotations:
            rotations = [base_rotation]

    if normal_mode == "current":
        normals = [base_normal]
    else:
        normals = normal_candidates(live_pair.vector, "auto")

    seen: set[tuple[int, int, int, int, int, int]] = set()
    result: list[dict] = []

    def add_candidate(offset: Vec3i, rotation: Vec3i, label: str, priority: int) -> None:
        key = offset.as_tuple() + rotation.as_tuple()
        if key in seen:
            return
        seen.add(key)
        result.append({
            "label": label,
            "offset": {"x": offset.x, "y": offset.y, "z": offset.z},
            "rotation": {"x": rotation.x, "y": rotation.y, "z": rotation.z},
            "priority": priority,
        })

    add_candidate(base_offset, base_rotation, "python-current", 0)

    # Try the exact analytically computed candidates first.
    priority = 10
    exact_candidates: list[tuple[Vec3i, Vec3i, Vec3i, str, int]] = []
    for rotation in rotations:
        transform = projection_rotation_transform(rotation)
        transformed_pair = projector_to_grid(transform(blueprint_pair.vector))
        if transformed_pair != live_pair.vector:
            continue
        for normal in normals:
            if normal.dot(live_pair.vector) != 0:
                continue
            target_merge = live_pair.merge.min + normal * contact_gap
            try:
                offset = compute_offset_for_target_with_rotation(
                    live_projector_min,
                    blueprint_projector_min,
                    blueprint_pair.merge.min,
                    target_merge,
                    transform,
                    anchor_mode,
                    grid_to_projector,
                )
            except Exception:
                continue
            exact_candidates.append((offset, rotation, normal, f"exact normal={normal} rot={rotation}", priority))
            priority += 1

    # Current predicted transform first, then the rest.
    for offset, rotation, normal, label, prio in exact_candidates:
        add_candidate(offset, rotation, label, prio)

    # Add small offset neighborhoods around each exact candidate. This compensates
    # for projector origin/model-origin differences without hardcoding them.
    for offset, rotation, normal, label, prio in exact_candidates:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    candidate_offset = Vec3i(offset.x + dx, offset.y + dy, offset.z + dz)
                    add_candidate(candidate_offset, rotation, f"near {label} d=({dx},{dy},{dz})", prio + 100)
                    if len(result) >= limit:
                        return result

    return result[:limit]


def run_projection_probe(
    projector: object,
    candidates: list[dict],
    *,
    wait: float,
    apply_best: bool,
    max_candidates: int,
) -> dict:
    if not candidates:
        print("Projection probe: no candidates generated")
        return {}

    print(f"Projection probe: sending {len(candidates)} candidates, apply_best={apply_best}")
    sender = getattr(projector, "send_command", None)
    if not callable(sender):
        print("Projection probe: projector.send_command is unavailable")
        return {}

    try:
        seq_id = sender({
            "cmd": "projection_probe",
            "state": {
                "candidates": candidates[:max_candidates],
                "applyBest": bool(apply_best),
                "restoreOriginal": not bool(apply_best),
                "maxCandidates": int(max_candidates),
            },
        })
        print(f"projection_probe request sent: seq_id={seq_id}")
    except Exception as exc:
        print(f"WARNING: projection_probe request failed: {exc}")
        return {}

    deadline = time.time() + max(0.1, float(wait))
    report: dict = {}
    while time.time() <= deadline:
        time.sleep(0.25)
        refresh_projector_telemetry(projector, timeout=0.75)
        getter = getattr(projector, "projection_report", None)
        if callable(getter):
            try:
                candidate_report = getter()
            except Exception:
                candidate_report = {}
            if isinstance(candidate_report, dict) and candidate_report.get("source") == "projection_probe_v36":
                report = candidate_report
                break

    if not report:
        print("Projection probe: no v36 probe report returned. Check that the v36 plugin is deployed and restarted.")
        telemetry = getattr(projector, "telemetry", None) or {}
        print(f"  supportsProjectionProbe: {telemetry.get('supportsProjectionProbe')}")
        print(f"  projectorContactReportVersion: {telemetry.get('projectorContactReportVersion')}")
        return {}

    print(
        "Projection probe result: "
        f"candidates={report.get('candidateCount')} bestIndex={report.get('bestIndex')} "
        f"bestBuildable={report.get('bestBuildableBlocks')} "
        f"bestRemaining={report.get('bestRemainingBlocks')} "
        f"bestOffset={report.get('bestOffset')} bestRotation={report.get('bestRotation')} "
        f"finalMode={report.get('finalMode')}"
    )
    results = report.get("results")
    if isinstance(results, list):
        def score(item: object) -> tuple[int, int, int]:
            if not isinstance(item, dict):
                return (-1, -1, -10**9)
            return (
                int(item.get("buildableBlocks") or 0),
                int(item.get("totalBlocks") or 0),
                -int(item.get("remainingBlocks") or 0),
            )
        top = sorted([item for item in results if isinstance(item, dict)], key=score, reverse=True)[:10]
        print("Projection probe top candidates:")
        for item in top:
            print(
                f"  #{item.get('index')} buildable={item.get('buildableBlocks')} "
                f"remaining={item.get('remainingBlocks')} total={item.get('totalBlocks')} "
                f"offset={item.get('requestedOffset')} rotation={item.get('requestedRotation')} "
                f"label={item.get('label')}"
            )
    return report



def _coerce_int_for_probe(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _vec_from_any_for_probe(value: object) -> Optional[Vec3i]:
    return telemetry_vec3(value)


def read_projector_telemetry_raw(projector: object, *, require_id: bool = True) -> dict:
    """Read the freshest projector telemetry directly from Redis.

    The normal BaseDevice object can be stale when the projector is located on an
    aggregated subgrid. This helper scans telemetry keys by entity id and updates
    ``projector.telemetry`` with the best snapshot it can find.
    """
    redis = getattr(projector, "redis", None)
    if redis is None:
        return getattr(projector, "telemetry", None) or {}

    device_id = projector_device_id(projector)
    candidates: list[str] = []
    key = getattr(projector, "telemetry_key", None)
    if key:
        candidates.append(str(key))

    raw_client = getattr(redis, "client", None) or getattr(redis, "_client", None)
    if device_id is not None and raw_client is not None:
        patterns = [
            f"*:{device_id}:telemetry",
            f"se:*:*:{device_id}:telemetry",
            f"se:*:grid:*:*:{device_id}:telemetry",
        ]
        for pattern in patterns:
            try:
                for raw_key in raw_client.scan_iter(match=pattern, count=100):
                    if isinstance(raw_key, bytes):
                        raw_key = raw_key.decode("utf-8", "replace")
                    key_text = str(raw_key)
                    if key_text not in candidates:
                        candidates.append(key_text)
            except Exception:
                pass

    best: dict = {}
    get_json = getattr(redis, "get_json", None)
    for key_text in candidates:
        if not callable(get_json):
            continue
        try:
            snapshot = get_json(key_text)
        except Exception:
            continue
        if not isinstance(snapshot, dict):
            continue
        if require_id and device_id is not None:
            sid = parse_int(snapshot.get("id") or snapshot.get("entityId") or snapshot.get("blockId"))
            if sid is not None and sid != device_id:
                continue
        # Prefer snapshots that actually contain projector-specific fields.
        if not best:
            best = snapshot
        score_new = sum(1 for k in ("offset", "rotation", "isProjecting", "totalBlocks", "buildableBlocks", "projectorContactReportVersion", "supportsProjectionProbe", "projectionReport") if k in snapshot)
        score_old = sum(1 for k in ("offset", "rotation", "isProjecting", "totalBlocks", "buildableBlocks", "projectorContactReportVersion", "supportsProjectionProbe", "projectionReport") if k in best)
        if score_new >= score_old:
            best = snapshot

    if best:
        try:
            projector.telemetry = best
        except Exception:
            pass
        return best
    return getattr(projector, "telemetry", None) or {}


def wait_for_projector_raw_transform(
    projector: object,
    expected_offset: Vec3i,
    expected_rotation: Vec3i,
    *,
    timeout: float,
    poll: float = 0.15,
) -> dict:
    deadline = time.time() + max(0.1, float(timeout))
    last: dict = {}
    while time.time() <= deadline:
        try:
            projector.update()
        except Exception:
            pass
        time.sleep(max(0.02, float(poll)))
        last = read_projector_telemetry_raw(projector)
        actual_offset = _vec_from_any_for_probe(last.get("offset"))
        actual_rotation = _vec_from_any_for_probe(last.get("rotation"))
        if actual_offset == expected_offset and actual_rotation == expected_rotation:
            return last
    return last or read_projector_telemetry_raw(projector)


def apply_projector_transform_absolute_no_fallback(
    projector: object,
    offset: Vec3i,
    rotation: Vec3i,
    *,
    wait: float,
    settle_after_match: float = 0.0,
) -> dict:
    """Set absolute projector transform without nudge/move fallback.

    The older fallback could over-shift if telemetry was late. During probing we
    must test exactly the requested candidate, so only absolute setters are used.
    After offset/rotation appear in telemetry, wait a little more because
    buildableBlocks/projectionReport often update one game tick later.
    """
    try:
        projector.set_rotation(rotation.x, rotation.y, rotation.z)
    except Exception as exc:
        print(f"WARNING: probe set_rotation failed for {rotation}: {exc}")
    time.sleep(0.05)
    try:
        projector.set_offset(offset.x, offset.y, offset.z)
    except Exception as exc:
        print(f"WARNING: probe set_offset failed for {offset}: {exc}")
    try:
        projector.set_enabled(True)
    except Exception:
        pass

    telemetry = wait_for_projector_raw_transform(projector, offset, rotation, timeout=wait)
    if settle_after_match > 0:
        time.sleep(float(settle_after_match))
        try:
            projector.update()
        except Exception:
            pass
        time.sleep(0.10)
        telemetry = read_projector_telemetry_raw(projector)
    return telemetry


def _projection_report_missing_entity_ids(telemetry: dict) -> set[int]:
    report = telemetry.get("projectionReport") if isinstance(telemetry, dict) else None
    if not isinstance(report, dict):
        return set()
    missing = report.get("missingBlocks")
    if not isinstance(missing, list):
        return set()
    result: set[int] = set()
    for item in missing:
        if not isinstance(item, dict):
            continue
        entity_id = parse_int(item.get("entityId") or item.get("entityID") or item.get("id"))
        if entity_id is not None:
            result.add(entity_id)
    return result


def _projection_report_has_missing_list(telemetry: dict) -> bool:
    report = telemetry.get("projectionReport") if isinstance(telemetry, dict) else None
    return isinstance(report, dict) and isinstance(report.get("missingBlocks"), list)


def _parse_terminal_remaining_block_counts(detailed_info: str) -> dict[str, int]:
    """Parse projector DetailedInfo "Blocks remaining" section.

    This is important because projector.BuildableBlocksCount can be >0 even for a
    visually wrong pose. The terminal text is produced by the game projector
    itself and tells which block display names are still missing after the live
    offset/rotation was applied.
    """
    text = str(detailed_info or "")
    result: dict[str, int] = {}
    in_section = False
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if "blocks remaining" in lower or "remaining blocks" in lower or "осталось блок" in lower:
            in_section = True
            continue
        if not in_section:
            continue
        if ":" not in line:
            # The section is usually a compact list of "Name: N" lines. Once a
            # new non-list section starts, stop parsing to avoid false positives.
            if result:
                break
            continue
        name, value = line.rsplit(":", 1)
        name = name.strip()
        value = value.strip()
        try:
            count = int(float(value.replace(",", ".")))
        except Exception:
            continue
        if name:
            result[name] = count
    return result


def _terminal_block_missing(counts: dict[str, int], kind: str) -> Optional[bool]:
    """Return whether a contact block kind is still listed in DetailedInfo."""
    if not counts:
        return None
    needles: tuple[str, ...]
    if kind == "merge":
        needles = ("merge", "мердж")
    elif kind == "connector":
        needles = ("connector", "коннектор", "соединител")
    else:
        return None
    for name, count in counts.items():
        lower = name.lower()
        if any(n in lower for n in needles):
            return count > 0
    return False


def _contact_probe_status(telemetry: dict, merge_entity_id: Optional[int], connector_entity_id: Optional[int]) -> dict:
    # First try the explicit projectionReport.missingBlocks entity list. In the
    # current plugin this list can be stale or untransformed, so do not rely on
    # it exclusively.
    report_known = _projection_report_has_missing_list(telemetry)
    missing_ids = _projection_report_missing_entity_ids(telemetry) if report_known else set()

    def report_status(entity_id: Optional[int]) -> Optional[bool]:
        if entity_id is None or not report_known:
            return None
        return entity_id in missing_ids

    report_merge_missing = report_status(merge_entity_id)
    report_connector_missing = report_status(connector_entity_id)

    # Stronger live signal: the game-generated projector DetailedInfo tells
    # which display names remain after the *actual* offset/rotation was applied.
    # This catches exactly the case where BuildableBlocksCount increases for a
    # wrong pose but Merge/Connector are still not aligned.
    terminal_counts = _parse_terminal_remaining_block_counts(str(telemetry.get("detailedInfo") or ""))
    terminal_merge_missing = _terminal_block_missing(terminal_counts, "merge")
    terminal_connector_missing = _terminal_block_missing(terminal_counts, "connector")

    merge_missing = terminal_merge_missing if terminal_merge_missing is not None else report_merge_missing
    connector_missing = terminal_connector_missing if terminal_connector_missing is not None else report_connector_missing
    known = merge_missing is not None or connector_missing is not None or report_known

    ready = 0
    if merge_missing is False:
        ready += 1
    if connector_missing is False:
        ready += 1
    missing_count = 0
    if merge_missing is True:
        missing_count += 1
    if connector_missing is True:
        missing_count += 1
    return {
        "contactStatusKnown": known,
        "contactStatusSource": "terminalDetailedInfo" if terminal_counts else ("projectionReport" if report_known else "unknown"),
        "mergeMissing": merge_missing,
        "connectorMissing": connector_missing,
        "terminalMergeMissing": terminal_merge_missing,
        "terminalConnectorMissing": terminal_connector_missing,
        "terminalMissingCounts": terminal_counts,
        "reportMergeMissing": report_merge_missing,
        "reportConnectorMissing": report_connector_missing,
        "contactReadyCount": ready,
        "contactMissingCount": missing_count,
    }


def _projection_probe_score(item: dict) -> tuple[int, int, int, int, int, int, int]:
    contact_ready = _coerce_int_for_probe(item.get("contactReadyCount"), 0)
    contact_known = 1 if bool(item.get("contactStatusKnown")) else 0
    buildable = _coerce_int_for_probe(item.get("buildableBlocks"), 0)
    total = _coerce_int_for_probe(item.get("totalBlocks"), 0)
    remaining = _coerce_int_for_probe(item.get("remainingBlocks"), 999999)
    is_projecting = 1 if bool(item.get("isProjecting")) else 0
    # Goal first: make the projected merge/connector not appear in missingBlocks.
    # Then prefer more buildable blocks and fewer remaining blocks.
    return (contact_ready, contact_known, buildable, is_projecting, total, -remaining, -_coerce_int_for_probe(item.get("index"), 999999))


def run_client_side_projection_probe(
    projector: object,
    candidates: list[dict],
    *,
    wait_per_candidate: float,
    settle_after_match: float,
    apply_best: bool,
    max_candidates: int,
    merge_entity_id: Optional[int],
    connector_entity_id: Optional[int],
) -> dict:
    if not candidates:
        print("Client projection probe: no candidates generated")
        return {}

    limit = min(len(candidates), max(0, int(max_candidates)))
    if limit <= 0:
        print("Client projection probe: candidate limit is zero")
        return {}

    original = read_projector_telemetry_raw(projector)
    original_offset = _vec_from_any_for_probe(original.get("offset")) or Vec3i(0, 0, 0)
    original_rotation = _vec_from_any_for_probe(original.get("rotation")) or Vec3i(0, 0, 0)

    print(
        f"Client projection probe: testing {limit} candidates by live set_offset/set_rotation; "
        f"original offset={original_offset}, rotation={original_rotation}; "
        f"wait={wait_per_candidate:.2f}s settle={settle_after_match:.2f}s; contact-aware scoring enabled"
    )

    results: list[dict] = []
    best: Optional[dict] = None
    last_best_buildable = -1

    for index, candidate in enumerate(candidates[:limit]):
        offset = candidate.get("offset")
        rotation = candidate.get("rotation")
        label = str(candidate.get("label") or "")
        if not isinstance(offset, dict) or not isinstance(rotation, dict):
            continue
        try:
            off = Vec3i(int(offset.get("x", 0)), int(offset.get("y", 0)), int(offset.get("z", 0)))
            rot = Vec3i(int(rotation.get("x", 0)), int(rotation.get("y", 0)), int(rotation.get("z", 0)))
        except Exception:
            continue

        telemetry = apply_projector_transform_absolute_no_fallback(
            projector,
            off,
            rot,
            wait=wait_per_candidate,
            settle_after_match=settle_after_match,
        )
        actual_offset = _vec_from_any_for_probe(telemetry.get("offset"))
        actual_rotation = _vec_from_any_for_probe(telemetry.get("rotation"))
        contact_status = _contact_probe_status(telemetry, merge_entity_id, connector_entity_id)
        item = {
            "index": index,
            "label": label,
            "requestedOffset": {"x": off.x, "y": off.y, "z": off.z},
            "requestedRotation": {"x": rot.x, "y": rot.y, "z": rot.z},
            "actualOffset": {"x": actual_offset.x, "y": actual_offset.y, "z": actual_offset.z} if actual_offset else None,
            "actualRotation": {"x": actual_rotation.x, "y": actual_rotation.y, "z": actual_rotation.z} if actual_rotation else None,
            "isProjecting": bool(telemetry.get("isProjecting")),
            "buildableBlocks": _coerce_int_for_probe(telemetry.get("buildableBlocks"), 0),
            "remainingBlocks": _coerce_int_for_probe(telemetry.get("remainingBlocks"), 0),
            "totalBlocks": _coerce_int_for_probe(telemetry.get("totalBlocks"), 0),
            **contact_status,
            "detailedInfo": str(telemetry.get("detailedInfo") or "")[:500],
        }
        results.append(item)
        if best is None or _projection_probe_score(item) > _projection_probe_score(best):
            best = item
            buildable = _coerce_int_for_probe(item.get("buildableBlocks"), 0)
            if buildable != last_best_buildable or index < 5:
                print(
                    f"  new best #{index}: contactReady={item.get('contactReadyCount')}/2 "
                    f"source={item.get('contactStatusSource')} mergeMissing={item.get('mergeMissing')} connectorMissing={item.get('connectorMissing')} "
                    f"buildable={item['buildableBlocks']} remaining={item['remainingBlocks']} "
                    f"total={item['totalBlocks']} offset={item['requestedOffset']} rotation={item['requestedRotation']} "
                    f"actualOffset={item.get('actualOffset')} actualRotation={item.get('actualRotation')} label={label}"
                )
                last_best_buildable = buildable

        if index < 5 or (index + 1) % 50 == 0:
            print(
                f"  probe #{index + 1}/{limit}: contactReady={item.get('contactReadyCount')}/2 "
                f"source={item.get('contactStatusSource')} mergeMissing={item.get('mergeMissing')} connectorMissing={item.get('connectorMissing')} "
                f"buildable={item['buildableBlocks']} remaining={item['remainingBlocks']} total={item['totalBlocks']} "
                f"offset={item['requestedOffset']} rotation={item['requestedRotation']} actualOffset={item.get('actualOffset')}"
            )

    if best is None:
        print("Client projection probe: no valid candidates were tested")
        return {}

    best_offset_dict = best.get("requestedOffset") or {}
    best_rotation_dict = best.get("requestedRotation") or {}
    best_offset = Vec3i(int(best_offset_dict.get("x", 0)), int(best_offset_dict.get("y", 0)), int(best_offset_dict.get("z", 0)))
    best_rotation = Vec3i(int(best_rotation_dict.get("x", 0)), int(best_rotation_dict.get("y", 0)), int(best_rotation_dict.get("z", 0)))

    if apply_best:
        final_telemetry = apply_projector_transform_absolute_no_fallback(
            projector, best_offset, best_rotation, wait=wait_per_candidate, settle_after_match=settle_after_match
        )
        final_mode = "best_applied_client"
    else:
        final_telemetry = apply_projector_transform_absolute_no_fallback(
            projector, original_offset, original_rotation, wait=wait_per_candidate, settle_after_match=settle_after_match
        )
        final_mode = "original_restored_client"

    report = {
        "source": "client_projection_probe_v39_terminal_contact",
        "candidateCount": len(results),
        "bestIndex": best.get("index"),
        "bestOffset": best.get("requestedOffset"),
        "bestRotation": best.get("requestedRotation"),
        "bestBuildableBlocks": best.get("buildableBlocks"),
        "bestRemainingBlocks": best.get("remainingBlocks"),
        "bestTotalBlocks": best.get("totalBlocks"),
        "finalMode": final_mode,
        "finalTelemetry": final_telemetry,
        "finalContactStatus": _contact_probe_status(final_telemetry, merge_entity_id, connector_entity_id),
        "results": results,
    }

    print(
        "Client projection probe result: "
        f"candidates={report['candidateCount']} bestIndex={report['bestIndex']} "
        f"bestContactReady={best.get('contactReadyCount')}/2 "
        f"bestContactSource={best.get('contactStatusSource')} "
        f"bestMergeMissing={best.get('mergeMissing')} bestConnectorMissing={best.get('connectorMissing')} "
        f"bestBuildable={report['bestBuildableBlocks']} bestRemaining={report['bestRemainingBlocks']} "
        f"bestOffset={report['bestOffset']} bestRotation={report['bestRotation']} "
        f"bestActualOffset={best.get('actualOffset')} bestActualRotation={best.get('actualRotation')} finalMode={final_mode} "
        f"finalContact={report['finalContactStatus']}"
    )
    top = sorted(results, key=_projection_probe_score, reverse=True)[:10]
    print("Client projection probe top candidates:")
    for item in top:
        print(
            f"  #{item.get('index')} contactReady={item.get('contactReadyCount')}/2 "
            f"source={item.get('contactStatusSource')} mergeMissing={item.get('mergeMissing')} connectorMissing={item.get('connectorMissing')} "
            f"buildable={item.get('buildableBlocks')} remaining={item.get('remainingBlocks')} total={item.get('totalBlocks')} "
            f"offset={item.get('requestedOffset')} rotation={item.get('requestedRotation')} "
            f"actualOffset={item.get('actualOffset')} actualRotation={item.get('actualRotation')} label={item.get('label')}"
        )
    return report

def finalize_blueprint(root: ET.Element, display_name: str) -> str:
    if "xmlns:xsd" not in root.attrib:
        root.attrib["xmlns:xsd"] = XSD_NS

    display = root.find("DisplayName")
    if display is None:
        display = ET.Element("DisplayName")
        id_node = root.find("Id")
        root.insert(1 if id_node is not None else 0, display)
    display.text = display_name

    id_node = root.find("Id")
    if id_node is None:
        id_node = ET.Element("Id")
        root.insert(0, id_node)
    id_node.attrib["Type"] = "MyObjectBuilder_ShipBlueprintDefinition"
    id_node.attrib["Subtype"] = display_name

    xml_body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + xml_body


def bool_from_telemetry(value: object) -> str:
    if value is None:
        return "?"
    return str(value)


def telemetry_vec3(value: object) -> Optional[Vec3i]:
    if isinstance(value, dict):
        x = parse_int(value.get("x") if "x" in value else value.get("X"))
        y = parse_int(value.get("y") if "y" in value else value.get("Y"))
        z = parse_int(value.get("z") if "z" in value else value.get("Z"))
        if x is not None and y is not None and z is not None:
            return Vec3i(x, y, z)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        x = parse_int(value[0])
        y = parse_int(value[1])
        z = parse_int(value[2])
        if x is not None and y is not None and z is not None:
            return Vec3i(x, y, z)
    return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_memory_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise ValueError("blueprint memory name must be non-empty")
    if len(value) > 160:
        raise ValueError("blueprint memory name is too long")
    return value


def blueprint_memory_prefix(owner_id: str, custom_prefix: str = "") -> str:
    if custom_prefix:
        return custom_prefix.rstrip(":")
    return f"se:{owner_id}:memory:projection_blueprints"


def blueprint_index_key(owner_id: str, custom_prefix: str = "") -> str:
    return f"{blueprint_memory_prefix(owner_id, custom_prefix)}:index"


def blueprint_item_key(owner_id: str, name: str, custom_prefix: str = "") -> str:
    digest = hashlib.sha1(safe_memory_name(name).encode("utf-8")).hexdigest()
    return f"{blueprint_memory_prefix(owner_id, custom_prefix)}:items:{digest}"


def redis_owner_id(explicit_owner_id: str = "") -> str:
    if explicit_owner_id:
        return str(explicit_owner_id)
    try:
        from secontrol.common import resolve_owner_id
        return str(resolve_owner_id())
    except Exception:
        env_value = os.environ.get("SE_OWNER_ID") or os.environ.get("REDIS_USERNAME")
        if env_value:
            return str(env_value)
        raise RuntimeError("Cannot resolve Redis owner id. Pass --redis-owner-id or set SE_OWNER_ID/REDIS_USERNAME")


def redis_client():
    from secontrol.redis_client import RedisEventClient
    return RedisEventClient()


def redis_get_index(client: object, owner_id: str, custom_prefix: str = "") -> dict:
    key = blueprint_index_key(owner_id, custom_prefix)
    payload = client.get_json(key)
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, dict):
            return payload
    return {"version": 1, "updatedAt": utc_now_iso(), "items": {}}


def redis_save_index(client: object, owner_id: str, index: dict, custom_prefix: str = "") -> None:
    index["updatedAt"] = utc_now_iso()
    client.set_json(blueprint_index_key(owner_id, custom_prefix), index)


def redis_load_blueprint_record(client: object, owner_id: str, name: str, custom_prefix: str = "") -> dict:
    name = safe_memory_name(name)
    index = redis_get_index(client, owner_id, custom_prefix)
    item = (index.get("items") or {}).get(name)
    key = item.get("key") if isinstance(item, dict) else None
    if not key:
        key = blueprint_item_key(owner_id, name, custom_prefix)
    record = client.get_json(key)
    if not isinstance(record, dict):
        raise KeyError(f"blueprint {name!r} not found in Redis memory")
    xml = record.get("xml")
    if not isinstance(xml, str) or "<" not in xml:
        raise ValueError(f"Redis blueprint {name!r} has no valid XML payload")
    return record


def redis_save_blueprint_record(
    client: object,
    owner_id: str,
    *,
    name: str,
    xml: str,
    source: str,
    grid_name: str = "",
    grid_id: str = "",
    custom_prefix: str = "",
) -> dict:
    name = safe_memory_name(name)
    tree = parse_blueprint_text(xml)
    root = tree.getroot()
    cube_grid = get_cube_grid(root)
    cube_blocks = get_cube_blocks(cube_grid)
    normalized_xml = finalize_blueprint(root, name)
    checksum = hashlib.sha256(normalized_xml.encode("utf-8")).hexdigest()
    now = utc_now_iso()
    key = blueprint_item_key(owner_id, name, custom_prefix)
    existing = client.get_json(key)
    created_at = existing.get("createdAt") if isinstance(existing, dict) and existing.get("createdAt") else now
    record = {
        "version": 1,
        "name": name,
        "source": source,
        "gridName": str(grid_name or ""),
        "gridId": str(grid_id or ""),
        "createdAt": created_at,
        "updatedAt": now,
        "blockCount": len(list(cube_blocks)),
        "gridSizeEnum": (cube_grid.findtext("GridSizeEnum") or "").strip(),
        "xmlSize": len(normalized_xml),
        "checksumSha256": checksum,
        "xml": normalized_xml,
    }
    client.set_json(key, record)
    index = redis_get_index(client, owner_id, custom_prefix)
    index.setdefault("items", {})[name] = {
        "name": name,
        "key": key,
        "source": source,
        "gridName": record["gridName"],
        "gridId": record["gridId"],
        "updatedAt": now,
        "blockCount": record["blockCount"],
        "xmlSize": record["xmlSize"],
        "checksumSha256": checksum,
    }
    redis_save_index(client, owner_id, index, custom_prefix)
    return record


def redis_delete_blueprint_record(client: object, owner_id: str, name: str, custom_prefix: str = "") -> bool:
    name = safe_memory_name(name)
    index = redis_get_index(client, owner_id, custom_prefix)
    item = (index.get("items") or {}).pop(name, None)
    key = item.get("key") if isinstance(item, dict) and item.get("key") else blueprint_item_key(owner_id, name, custom_prefix)
    deleted = False
    raw = getattr(client, "_client", None)
    if raw is not None:
        deleted = bool(raw.delete(key))
    else:
        client.set_json(key, None)
        deleted = True
    redis_save_index(client, owner_id, index, custom_prefix)
    return deleted or item is not None


def redis_list_blueprints(client: object, owner_id: str, custom_prefix: str = "") -> list[dict]:
    index = redis_get_index(client, owner_id, custom_prefix)
    items = index.get("items") or {}
    if not isinstance(items, dict):
        return []
    result = []
    for name, item in items.items():
        if isinstance(item, dict):
            result.append(item)
        else:
            result.append({"name": name})
    result.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return result


def wait_for_grid_blueprint_xml(projector: object, timeout: float) -> str:
    deadline = time.time() + timeout
    last_size = 0
    while time.time() < deadline:
        try:
            xml = projector.blueprint_xml()
            if isinstance(xml, str) and "<MyObjectBuilder_ShipBlueprintDefinition" in xml:
                return xml
            if isinstance(xml, str):
                last_size = len(xml)
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"grid blueprint export did not produce XML within {timeout:g}s; last xml size={last_size}")


def telemetry_int_value(telemetry: dict, *names: str) -> Optional[int]:
    for name in names:
        value = telemetry.get(name)
        parsed = parse_int(value)
        if parsed is not None:
            return parsed
    return None


def clear_existing_projector_blueprint(projector: object, *, wait_timeout: float, attempts: int = 2) -> None:
    print("Clearing existing projector blueprint/projection before loading new XML...")
    try:
        refresh_projector_telemetry(projector, timeout=0.75)
    except Exception:
        pass
    before = getattr(projector, "telemetry", None) or {}
    print(
        "Projector state before clear: "
        f"isProjecting={before.get('isProjecting')}, "
        f"totalBlocks={before.get('totalBlocks')}, "
        f"remainingBlocks={before.get('remainingBlocks')}, "
        f"buildableBlocks={before.get('buildableBlocks')}"
    )

    try:
        projector.set_enabled(False)
        time.sleep(0.2)
    except Exception as exc:
        print(f"WARNING: projector disable before clear failed: {exc}")

    for attempt in range(1, max(1, attempts) + 1):
        print(f"Clear attempt {attempt}/{max(1, attempts)}")
        for method_name in ("clear_projection", "delete_projection", "clear_blueprint", "reset_projection"):
            method = getattr(projector, method_name, None)
            if not callable(method):
                continue
            try:
                seq_id = method()
                print(f"{method_name} sent: seq_id={seq_id}")
            except Exception as exc:
                print(f"WARNING: {method_name} failed: {exc}")
            time.sleep(0.45)
            refresh_projector_telemetry(projector, timeout=0.75)
            telemetry = getattr(projector, "telemetry", None) or {}
            total = telemetry_int_value(telemetry, "totalBlocks", "total")
            remaining = telemetry_int_value(telemetry, "remainingBlocks", "remaining")
            buildable = telemetry_int_value(telemetry, "buildableBlocks", "buildable")
            is_projecting = telemetry.get("isProjecting")
            has_projection_fields = any(name in telemetry for name in ("isProjecting", "totalBlocks", "remainingBlocks", "buildableBlocks"))
            if has_projection_fields and (total in (None, 0)) and (remaining in (None, 0)) and (buildable in (None, 0)) and not bool(is_projecting):
                print("Projector clear confirmed by telemetry")
                try:
                    projector.set_offset(0, 0, 0)
                    projector.set_rotation(0, 0, 0)
                except Exception:
                    pass
                return
            if not has_projection_fields:
                print("WARNING: projector telemetry has no projection fields; clear cannot be confirmed from telemetry")

    telemetry = getattr(projector, "telemetry", None) or {}
    print(
        "WARNING: projector clear was not fully confirmed; continuing with load. "
        f"isProjecting={telemetry.get('isProjecting')}, "
        f"totalBlocks={telemetry.get('totalBlocks')}, "
        f"remainingBlocks={telemetry.get('remainingBlocks')}, "
        f"buildableBlocks={telemetry.get('buildableBlocks')}"
    )
    try:
        projector.set_offset(0, 0, 0)
        projector.set_rotation(0, 0, 0)
    except Exception:
        pass


def refresh_projector_telemetry(projector: object, timeout: float = 1.0) -> None:
    waiter = getattr(projector, "wait_for_telemetry", None)
    if callable(waiter):
        try:
            waiter(timeout=timeout, wait_for_new=True, need_update=True)
            return
        except Exception:
            pass
    try:
        projector.update()
    except Exception:
        pass
    time.sleep(min(timeout, 0.5))


def current_projector_offset(projector: object) -> Optional[Vec3i]:
    telemetry = getattr(projector, "telemetry", None) or {}
    return telemetry_vec3(telemetry.get("offset"))


def current_projector_rotation(projector: object) -> Optional[Vec3i]:
    telemetry = getattr(projector, "telemetry", None) or {}
    return telemetry_vec3(telemetry.get("rotation"))


def wait_for_projector_rotation(projector: object, expected: Vec3i, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        refresh_projector_telemetry(projector, timeout=0.75)
        actual = current_projector_rotation(projector)
        if actual == expected:
            return True
        time.sleep(0.15)
    return False


def wait_for_projector_offset(projector: object, expected: Vec3i, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        refresh_projector_telemetry(projector, timeout=0.75)
        actual = current_projector_offset(projector)
        if actual == expected:
            return True
        time.sleep(0.15)
    return False


def apply_projector_transform(projector: object, offset: Vec3i, rotation: Vec3i, wait_timeout: float) -> None:
    try:
        projector.set_flags(
            keep_projection=True,
            show_only_buildable=False,
            align_grids=False,
            lock_projection=False,
            use_adaptive_offsets=False,
            use_adaptive_rotation=False,
        )
    except Exception as exc:
        print(f"WARNING: projector flags were not fully applied: {exc}")

    # Some plugin builds do not expose every projector checkbox through set_flags(),
    # so send a raw fallback too. This prevents the common "blocks disappeared"
    # symptom when Show Only Buildable remains enabled on the live projector.
    try:
        projector.send_command({
            "cmd": "projector_state",
            "state": {
                "showOnlyBuildable": False,
                "ShowOnlyBuildable": False,
                "markMissingBlocks": False,
                "MarkMissingBlocks": False,
                "markUnfinishedBlocks": False,
                "MarkUnfinishedBlocks": False,
            },
        })
        print("Projector visibility flags requested: showOnlyBuildable=False, markMissingBlocks=False")
    except Exception as exc:
        print(f"WARNING: raw projector visibility flags failed: {exc}")

    time.sleep(0.25)
    refresh_projector_telemetry(projector, timeout=0.75)
    before_rotation = current_projector_rotation(projector)
    before_offset = current_projector_offset(projector)
    print(f"Current projector rotation before apply: {before_rotation}")
    print(f"Current projector offset before apply:   {before_offset}")

    seq_id = projector.set_rotation(rotation.x, rotation.y, rotation.z)
    print(f"set_rotation sent: seq_id={seq_id}, target={rotation}")
    if wait_for_projector_rotation(projector, rotation, wait_timeout):
        print(f"Rotation confirmed by telemetry: {rotation}")
    else:
        actual_rotation = current_projector_rotation(projector)
        print(f"WARNING: projector rotation was not confirmed; expected={rotation}, actual={actual_rotation}")

    seq_id = projector.set_offset(offset.x, offset.y, offset.z)
    print(f"set_offset sent: seq_id={seq_id}, target={offset}")
    if wait_for_projector_offset(projector, offset, wait_timeout):
        print(f"Offset confirmed by telemetry: {offset}")
        return

    actual = current_projector_offset(projector)
    print(f"WARNING: absolute set_offset was not confirmed; expected={offset}, actual={actual}")

    if actual is not None:
        delta = offset - actual
    else:
        delta = offset

    if delta != Vec3i(0, 0, 0):
        try:
            seq_id = projector.move_offset(delta.x, delta.y, delta.z)
            print(f"move_offset fallback sent: seq_id={seq_id}, delta={delta}")
        except Exception as exc:
            print(f"WARNING: move_offset fallback failed: {exc}")
        if wait_for_projector_offset(projector, offset, wait_timeout):
            print(f"Offset confirmed after move fallback: {offset}")
            return

    try:
        seq_id = projector.send_command({
            "cmd": "set_offset",
            "payload": {"x": offset.x, "y": offset.y, "z": offset.z},
        })
        print(f"raw payload set_offset fallback sent: seq_id={seq_id}, target={offset}")
    except Exception as exc:
        print(f"WARNING: raw payload fallback failed: {exc}")
    if not wait_for_projector_offset(projector, offset, wait_timeout):
        actual = current_projector_offset(projector)
        print(f"WARNING: projector offset still not confirmed; expected={offset}, actual={actual}")



def embed_projector_transform(blocks: list[BlueprintBlock], offset: Vec3i, rotation: Vec3i) -> int:
    """Write ProjectionOffset/ProjectionRotation into every projector block in XML."""
    count = 0
    for block in blocks:
        if not is_projector_type(block.block_type, block.subtype):
            continue
        ensure_projection_vector(block.element, "ProjectionOffset", offset)
        ensure_projection_vector(block.element, "ProjectionRotation", rotation)
        count += 1
    return count


def shift_blueprint_blocks(
    blocks: list[BlueprintBlock],
    shift: Vec3i,
    *,
    skip_anchor_projector: Optional[BlueprintBlock] = None,
) -> int:
    """Move prepared blocks by an integer grid shift inside the XML itself.

    Space Engineers ignores a uniform translation of the entire blueprint when it
    creates a projection. The relative geometry around the loaded projector
    anchor is what matters. For contact placement we therefore keep the anchor
    projector cell fixed and shift the projected ship relative to it.
    """
    if shift == Vec3i(0, 0, 0):
        return 0
    moved = 0
    for block in blocks:
        if skip_anchor_projector is not None and block is skip_anchor_projector:
            continue
        block.min = block.min + shift
        set_min(block.element, block.min)
        moved += 1
    return moved


def count_min_cell_collisions(blocks: list[BlueprintBlock], live_blocks: list[LiveBlock]) -> int:
    live_occupied = {block.min for block in live_blocks}
    return sum(1 for block in blocks if block.min in live_occupied)



def count_projected_min_cell_collisions(
    blocks: list[BlueprintBlock],
    live_blocks: list[LiveBlock],
    live_projector_min: Vec3i,
    blueprint_projector_min: Vec3i,
    offset: Vec3i,
    anchor_mode: str,
    projector_to_grid: Rotation,
) -> int:
    live_occupied = {block.min for block in live_blocks}
    return sum(
        1
        for block in blocks
        if predicted_position(live_projector_min, blueprint_projector_min, block.min, offset, anchor_mode, projector_to_grid) in live_occupied
    )


def matrix_from_telemetry(projector: object) -> Optional[list[list[float]]]:
    telemetry = getattr(projector, "telemetry", None) or {}
    matrix = telemetry.get("projectionMatrix")
    if not isinstance(matrix, list) or len(matrix) < 4:
        return None
    result: list[list[float]] = []
    try:
        for row in matrix[:4]:
            if not isinstance(row, list) or len(row) < 4:
                return None
            result.append([float(row[0]), float(row[1]), float(row[2]), float(row[3])])
    except (TypeError, ValueError):
        return None
    return result


def matrix_translation(matrix: list[list[float]]) -> tuple[float, float, float]:
    # VRage MatrixD stores translation in M41/M42/M43, i.e. row 4 columns 1..3.
    return matrix[3][0], matrix[3][1], matrix[3][2]


def matrix_basis(matrix: list[list[float]]) -> list[tuple[float, float, float]]:
    # Rows are Right(+X), Up(+Y), Backward(+Z) in the grid's local coordinate frame.
    return [
        (matrix[0][0], matrix[0][1], matrix[0][2]),
        (matrix[1][0], matrix[1][1], matrix[1][2]),
        (matrix[2][0], matrix[2][1], matrix[2][2]),
    ]


def float_vec_sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def float_dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def float_norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(float_dot(a, a))


def normalize_float_vec(a: tuple[float, float, float]) -> Optional[tuple[float, float, float]]:
    n = float_norm(a)
    if n <= 1e-6:
        return None
    return a[0] / n, a[1] / n, a[2] / n


def grid_axis_from_world_delta(
    delta: tuple[float, float, float],
    basis: list[tuple[float, float, float]],
) -> Optional[Vec3i]:
    delta_n = normalize_float_vec(delta)
    if delta_n is None:
        return None

    best_axis = -1
    best_score = 0.0
    for index, axis_world in enumerate(basis):
        axis_n = normalize_float_vec(axis_world)
        if axis_n is None:
            continue
        score = float_dot(delta_n, axis_n)
        if abs(score) > abs(best_score):
            best_score = score
            best_axis = index

    if best_axis < 0 or abs(best_score) < 0.65:
        return None

    sign = 1 if best_score > 0 else -1
    if best_axis == 0:
        return Vec3i(sign, 0, 0)
    if best_axis == 1:
        return Vec3i(0, sign, 0)
    return Vec3i(0, 0, sign)


def invert_projector_axis_map(ui_to_grid: dict[str, Vec3i], desired_grid_offset: Vec3i) -> Optional[Vec3i]:
    if set(ui_to_grid) != {"x", "y", "z"}:
        return None
    vectors = [ui_to_grid["x"], ui_to_grid["y"], ui_to_grid["z"]]
    occupied_axes = [v.axis_name() for v in vectors]
    if sorted(occupied_axes) != ["x", "y", "z"]:
        return None
    return Vec3i(
        desired_grid_offset.dot(ui_to_grid["x"]),
        desired_grid_offset.dot(ui_to_grid["y"]),
        desired_grid_offset.dot(ui_to_grid["z"]),
    )


def calibrate_projector_offset_axes(
    projector: object,
    calibration_xml: str,
    desired_grid_offset: Vec3i,
    projection_rotation: Vec3i,
    *,
    wait_after_load: float,
    wait_timeout: float,
    skip_reset: bool,
) -> Optional[Vec3i]:
    """Convert grid-space offset into projector UI offset by measuring ProjectionMatrix."""
    print("Calibrating projector offset axes from ProjectionMatrix...")
    try:
        if not skip_reset:
            projector.reset_projection()
            time.sleep(0.35)
        seq_id = projector.load_blueprint_xml(calibration_xml, keep=False)
        print(f"calibration load_blueprint_xml sent: seq_id={seq_id}")
        time.sleep(wait_after_load)
        apply_projector_transform(projector, Vec3i(0, 0, 0), projection_rotation, wait_timeout)
        refresh_projector_telemetry(projector, timeout=1.0)
    except Exception as exc:
        print(f"WARNING: offset-axis calibration setup failed: {exc}")
        return None

    base_matrix = matrix_from_telemetry(projector)
    if base_matrix is None:
        print("WARNING: ProjectionMatrix is not available; using grid offset as projector offset")
        return None

    base_translation = matrix_translation(base_matrix)
    base_basis = matrix_basis(base_matrix)
    ui_to_grid: dict[str, Vec3i] = {}
    probes = [("x", Vec3i(1, 0, 0)), ("y", Vec3i(0, 1, 0)), ("z", Vec3i(0, 0, 1))]

    for name, offset in probes:
        try:
            seq_id = projector.set_offset(offset.x, offset.y, offset.z)
            print(f"calibration probe {name}: set_offset seq_id={seq_id}, offset={offset}")
            if not wait_for_projector_offset(projector, offset, wait_timeout):
                print(f"WARNING: calibration probe {name} offset was not confirmed")
            refresh_projector_telemetry(projector, timeout=1.0)
        except Exception as exc:
            print(f"WARNING: calibration probe {name} failed: {exc}")
            return None

        matrix = matrix_from_telemetry(projector)
        if matrix is None:
            print(f"WARNING: ProjectionMatrix disappeared during probe {name}")
            return None
        delta = float_vec_sub(matrix_translation(matrix), base_translation)
        grid_axis = grid_axis_from_world_delta(delta, base_basis)
        if grid_axis is None:
            print(f"WARNING: cannot map projector UI axis {name}; world delta={delta}")
            return None
        ui_to_grid[name] = grid_axis
        print(f"calibration mapping: projector {name.upper()} +1 -> grid {grid_axis}")

    try:
        projector.set_offset(0, 0, 0)
        wait_for_projector_offset(projector, Vec3i(0, 0, 0), wait_timeout)
    except Exception:
        pass

    projector_offset = invert_projector_axis_map(ui_to_grid, desired_grid_offset)
    if projector_offset is None:
        print(f"WARNING: invalid projector axis map: {ui_to_grid}; using grid offset as projector offset")
        return None

    print(f"Grid-space offset requested:       {desired_grid_offset}")
    print(f"Projector UI offset after mapping: {projector_offset}")
    return projector_offset


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return result


def non_negative_int(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return result


def normalize_argv(argv: list[str]) -> list[str]:
    """Allow argparse to accept values like `--normal -z`.

    Standard argparse treats `-z` as another option instead of the value of
    `--normal`. PowerShell users naturally type `--normal -z`, so convert only
    this exact case to the safe `--normal=-z` form before parsing.
    """
    result: list[str] = []
    index = 0
    negative_normals = {"-x", "-y", "-z"}
    negative_value_options = {
        "--normal",
        "--manual-offset",
        "--manual-rotation",
        "--blueprint-projector-min",
        "--projector-ui-correction",
    }
    while index < len(argv):
        item = argv[index]
        if item in negative_value_options and index + 1 < len(argv) and argv[index + 1].startswith("-"):
            if item == "--normal" and argv[index + 1] not in negative_normals:
                result.append(item)
                index += 1
                continue
            result.append(f"{item}={argv[index + 1]}")
            index += 2
            continue
        result.append(item)
        index += 1
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load a Space Engineers clone blueprint and align its merge/connector contact by projector offset.",
    )
    parser.add_argument("grid", help="Main grid name or id, for example skynet-agent0")
    parser.add_argument("blueprint", nargs="?", default="", help="Path to bp.sbc, blueprint directory, or zip that contains bp.sbc. If omitted, the script tries %%APPDATA%%/SpaceEngineers/Blueprints/local/<grid>/bp.sbc")
    parser.add_argument("--output", default="", help="Write prepared XML to this file")
    parser.add_argument("--contact-tag", default="", help="Prefer merge/connector blocks whose name/type/subtype/entity id contains this text")
    parser.add_argument("--projector-name", default="", help="Use projector whose name contains this text")
    parser.add_argument("--projector-subtype", default="", help="Use projector whose block subtype contains this text, for example SmallProjector or LargeProjector. Useful when a grid has multiple projectors (e.g. one large and one on a rotor subgrid) and the name filter cannot disambiguate them")
    parser.add_argument("--display-name", default="", help="Display name for the temporary prepared blueprint")
    parser.add_argument("--grid-step", type=positive_float, default=0.0, help="Override block size in meters: 2.5 for large grid, 0.5 for small grid")
    parser.add_argument("--contact-mode", choices=("opposite", "overlay"), default="opposite", help="opposite places projection one contact gap beside the live blocks; overlay puts it on the same cells")
    parser.add_argument("--rotation-mode", choices=("projector", "xml"), default="projector", help="projector preserves all original block Min/BlockOrientation values and uses vanilla ProjectionRotation; xml rewrites every block and is only a legacy fallback")
    parser.add_argument("--anchor-mode", choices=("projector-block", "projector-origin", "grid-origin"), default="projector-block", help="legacy offset calculation mode used only when --placement-apply=offset")
    parser.add_argument("--placement-apply", choices=("offset", "xml"), default="offset", help="offset preserves blueprint geometry and moves the loaded projection with ProjectionOffset; xml bakes the contact shift into block Min coordinates and is only a legacy fallback")
    parser.add_argument("--projector-ui-correction", type=parse_vec3i_text, default=None, help="Additional SmallProjector model-origin correction vector, for example -1,-1,0. This is separate from --manual-offset and is intended for projector model origin correction.")
    parser.add_argument("--projector-ui-correction-space", choices=("auto", "ui", "rotated", "none"), default="auto", help="How to apply projector-ui-correction. auto disables correction for native ProjectionRotation and uses raw UI correction for XML-baked placement; ui keeps legacy behaviour; rotated rotates the correction by ProjectionRotation; none ignores it.")
    parser.add_argument("--no-small-projector-correction", action="store_true", help="Disable the automatic SmallProjector UI origin correction (-1,-1,0)")
    parser.add_argument("--drop-synthetic-projector-blocks", action="store_true", help="Remove projector blocks that had no Min in the source blueprint after using them only as placement anchors. Useful when the prepared projection contains one fake/colliding projector block")
    parser.add_argument("--strip-nonessential", action="store_true", help="Strip non-essential block XML tags. Disabled by default because projector blueprints are more reliable with full block XML")
    parser.add_argument("--keep-full-xml", action="store_true", help="Compatibility flag; full XML is preserved by default")
    parser.add_argument("--calibrate-offset-axes", dest="no_calibrate_offset_axes", action="store_false", help="Try to measure projector local offset axes through ProjectionMatrix. Usually unavailable on dedicated servers")
    parser.add_argument("--no-calibrate-offset-axes", dest="no_calibrate_offset_axes", action="store_true", default=True, help="Do not measure projector local offset axes; enabled by default because ProjectionMatrix is usually unavailable")
    parser.add_argument("--contact-gap", type=non_negative_int, default=1, help="Grid-cell gap for opposite mode. For face-to-face merge/connector use 1")
    parser.add_argument("--normal", choices=("auto", "+x", "-x", "+y", "-y", "+z", "-z", "x", "y", "z"), default="auto", help="Contact side for opposite mode. Use --normal=-z or --normal -z for negative directions; auto chooses the side with least collision")
    parser.add_argument("--merge-mate-face", choices=("auto",) + MERGE_MATE_FACE_CHOICES, default="auto", help="Which model face of the blueprint Merge Block is the real mating plate. Default auto selects the face that points back along the selected contact normal.")
    parser.add_argument("--no-preflip", action="store_true", help="Do not rotate blueprint 180 degrees around the merge/connector line before applying offset")
    parser.add_argument("--blueprint-projector-min", type=parse_vec3i_text, default=None, help="Manual projector anchor inside blueprint, for example 0,1,0")
    parser.add_argument("--projector-forward", type=parse_direction_arg, default=None, help="Manual live projector BlockOrientation Forward axis, for example Forward, Backward, Left, Right, Up, Down")
    parser.add_argument("--projector-up", type=parse_direction_arg, default=None, help="Manual live projector BlockOrientation Up axis, for example Forward, Backward, Left, Right, Up, Down")
    parser.add_argument("--ignore-projector-orientation", action="store_true", help="Use old grid-axis math and ignore live projector orientation")
    parser.add_argument("--no-upload", action="store_true", help="Only generate/check prepared XML; do not call projector.load_blueprint_xml")
    parser.add_argument("--offline", action="store_true", help="Do not connect to Redis/game; use blueprint contact pair and projector anchor as the live target and skip upload")
    parser.add_argument("--keep", action="store_true", help="Pass keep=True to load_blueprint_xml")
    parser.add_argument("--wait", type=positive_float, default=2.0, help="Seconds to wait after load before telemetry check")
    parser.add_argument("--offset-wait", type=positive_float, default=4.0, help="Seconds to wait for offset telemetry confirmation")
    parser.add_argument("--runtime-transform-mode", choices=("auto", "apply", "none"), default="auto", help="How to handle set_offset/set_rotation after load. auto skips runtime re-apply when the final transform was embedded into XML, because some projector bridges apply the embedded transform during load and then rotate again when set_rotation is sent.")
    parser.add_argument("--wake-timeout", type=positive_float, default=3.0, help="Seconds to wait while waking the grid")
    parser.add_argument("--skip-reset", action="store_true", help="Do not call reset_projection before loading")
    parser.add_argument("--manual-offset", type=parse_vec3i_text, default=None, help="Override calculated ProjectionOffset, for example 0,0,-1")
    parser.add_argument("--manual-rotation", type=parse_vec3i_text, default=None, help="Override calculated ProjectionRotation steps, for example 2,0,0")
    parser.add_argument("--skip-clear-existing", action="store_true", help="Do not clear/delete already loaded projector blueprint before loading the new one")
    parser.add_argument("--clear-timeout", type=positive_float, default=5.0, help="Seconds to wait for clearing the old projector blueprint")
    parser.add_argument("--redis-owner-id", default="", help="Owner id for Redis projection-blueprint memory. Defaults to SE_OWNER_ID/REDIS_USERNAME")
    parser.add_argument("--redis-prefix", default="", help="Override Redis memory prefix. Default: se:<owner>:memory:projection_blueprints")
    parser.add_argument("--redis-list", action="store_true", help="List saved projection blueprints in Redis and exit")
    parser.add_argument("--redis-load", default="", help="Load blueprint XML from Redis memory by name instead of file")
    parser.add_argument("--redis-save-file", default="", help="Save blueprint XML from the file argument to Redis under this name and exit")
    parser.add_argument("--redis-save-grid", default="", help="Export blueprint from the live grid projector, save it to Redis under this name, and exit")
    parser.add_argument("--redis-delete", default="", help="Delete saved blueprint from Redis by name and exit")
    parser.add_argument("--redis-export", nargs=2, metavar=("NAME", "OUTPUT"), default=None, help="Export saved Redis blueprint by name to a local .sbc file and exit")
    parser.add_argument("--grid-export-timeout", type=positive_float, default=15.0, help="Seconds to wait for --redis-save-grid export result")
    parser.add_argument("--no-grid-export-include-connected", action="store_true", help="When saving from grid, export only the projector grid, not connected grids")
    parser.add_argument("--no-live-blueprint-frame", action="store_true", help="Do not export the live grid before placement. By default the script reads live projector Min/BlockOrientation from a fresh grid blueprint export so projector position and rotation are part of the math.")
    parser.add_argument("--live-frame-include-connected", action="store_true", help="When reading the live projector frame, include connected grids in the temporary export. Default is only the projector grid to avoid mixing coordinate frames.")
    parser.add_argument("--verify-contact", choices=("on", "off"), default="on", help="Verify that the final projected Merge/Connector cells match the target live contact cells before upload")
    parser.add_argument("--strict-contact-verify", action="store_true", help="Abort before upload if the calculated contact verification fails")
    parser.add_argument("--no-projection-report-after-load", action="store_true", help="Do not request projection_report after loading the blueprint")
    parser.add_argument("--projection-report-wait", type=positive_float, default=3.0, help="Seconds to wait for projection_report after load")
    parser.add_argument("--projection-report-max-blocks", type=non_negative_int, default=300, help="Maximum blocks requested from projection_report diagnostics")
    parser.add_argument("--projection-report-output", default="", help="Optional path to save raw projection_report JSON; default writes next to the prepared .sbc when a report is returned")
    parser.add_argument("--projection-probe", action="store_true", help="After loading, ask the v36 plugin to test multiple offset/rotation candidates in the live game and rank them by BuildableBlocksCount")
    parser.add_argument("--projection-probe-radius", type=non_negative_int, default=1, help="Offset search radius around each calculated candidate for --projection-probe")
    parser.add_argument("--projection-probe-max-candidates", type=non_negative_int, default=500, help="Maximum live projector candidates sent to the plugin probe")
    parser.add_argument("--projection-probe-wait", type=positive_float, default=8.0, help="Seconds to wait for v36 projection_probe report")
    parser.add_argument("--projection-probe-rotations", choices=("current", "contact", "all"), default="contact", help="Which ProjectionRotation candidates to test: current, contact-vector-preserving, or all 64 UI rotations")
    parser.add_argument("--projection-probe-normals", choices=("current", "all"), default="all", help="Which contact side normals to test during --projection-probe")
    parser.add_argument("--no-projection-probe-apply-best", action="store_true", help="Do not leave the best live-tested candidate applied; restore original transform instead")
    parser.add_argument("--projection-probe-mode", choices=("auto", "plugin", "client"), default="auto", help="Use v36 plugin-side probe, Python client-side probe, or auto fallback to client when plugin report is not returned")
    parser.add_argument("--projection-probe-client-wait", type=positive_float, default=0.75, help="Seconds to wait until offset/rotation telemetry matches each client-side probe candidate")
    parser.add_argument("--projection-probe-client-settle", type=positive_float, default=0.75, help="Extra seconds to wait after offset/rotation match so buildableBlocks and projectionReport settle")
    return parser


def main() -> int:
    print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
    args = build_arg_parser().parse_args(normalize_argv(sys.argv[1:]))
    temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    grid = None
    live_projector: Optional[LiveBlock] = None
    live_projector_id: Optional[int] = None
    live_projector_min: Optional[Vec3i] = None
    projector_ui_correction = Vec3i(0, 0, 0)

    try:
        owner_id_for_redis = ""
        client_for_redis = None
        if any((
            args.redis_list,
            args.redis_load,
            args.redis_save_file,
            args.redis_save_grid,
            args.redis_delete,
            args.redis_export,
        )):
            owner_id_for_redis = redis_owner_id(args.redis_owner_id)
            client_for_redis = redis_client()

        if args.redis_list:
            items = redis_list_blueprints(client_for_redis, owner_id_for_redis, args.redis_prefix)
            print(f"Redis projection blueprint memory: {blueprint_memory_prefix(owner_id_for_redis, args.redis_prefix)}")
            if not items:
                print("No saved blueprints")
                return 0
            for index, item in enumerate(items, 1):
                print(
                    f"{index:02d}. {item.get('name')} | source={item.get('source', '?')} | "
                    f"grid={item.get('gridName') or item.get('gridId') or '-'} | "
                    f"blocks={item.get('blockCount', '?')} | size={item.get('xmlSize', '?')} | "
                    f"updated={item.get('updatedAt', '?')}"
                )
            return 0

        if args.redis_delete:
            deleted = redis_delete_blueprint_record(client_for_redis, owner_id_for_redis, args.redis_delete, args.redis_prefix)
            print(f"Redis blueprint deleted: {args.redis_delete} ({'found' if deleted else 'not found in item key, index cleaned'})")
            return 0

        if args.redis_export:
            name, output_text = args.redis_export
            record = redis_load_blueprint_record(client_for_redis, owner_id_for_redis, name, args.redis_prefix)
            output_path = Path(output_text).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(str(record['xml']), encoding="utf-8")
            print(f"Exported Redis blueprint '{name}' to {output_path}")
            return 0

        projector = None
        live_blocks: list[LiveBlock] = []
        live_by_entity_map: dict[int, LiveBlock] = {}
        live_projector_min: Optional[Vec3i] = None
        live_projector_id: Optional[int] = None

        if args.redis_save_grid:
            from secontrol.common import prepare_grid

            grid = prepare_grid(args.grid, auto_wake=True, wake_timeout=args.wake_timeout)
            grid.refresh_devices()
            projector = find_projector(grid, args.projector_name, args.projector_subtype)
            include_connected = not args.no_grid_export_include_connected
            seq_id = projector.request_grid_blueprint(include_connected=include_connected)
            print(f"request_grid_blueprint sent: seq_id={seq_id}, include_connected={include_connected}")
            xml_from_grid = wait_for_grid_blueprint_xml(projector, args.grid_export_timeout)
            record = redis_save_blueprint_record(
                client_for_redis,
                owner_id_for_redis,
                name=args.redis_save_grid,
                xml=xml_from_grid,
                source="grid",
                grid_name=str(getattr(grid, 'name', '') or ''),
                grid_id=str(getattr(grid, 'grid_id', '') or ''),
                custom_prefix=args.redis_prefix,
            )
            print(
                f"Saved grid blueprint to Redis: name={record['name']}, blocks={record['blockCount']}, "
                f"size={record['xmlSize']}, checksum={record['checksumSha256'][:12]}..."
            )
            return 0

        blueprint_arg = args.blueprint
        blueprint_path: Optional[Path] = None
        blueprint_source_description = ""

        if args.redis_load:
            record = redis_load_blueprint_record(client_for_redis, owner_id_for_redis, args.redis_load, args.redis_prefix)
            tree = parse_blueprint_text(str(record["xml"]))
            blueprint_arg = args.redis_load
            blueprint_source_description = f"Redis blueprint: {args.redis_load}"
            print(
                f"Loaded blueprint from Redis: name={record.get('name')}, "
                f"blocks={record.get('blockCount')}, size={record.get('xmlSize')}, "
                f"checksum={str(record.get('checksumSha256', ''))[:12]}..."
            )
        else:
            if not blueprint_arg:
                appdata = os.environ.get("APPDATA")
                if not appdata:
                    raise ValueError("blueprint path is required because APPDATA is not set")
                blueprint_arg = str(Path(appdata) / "SpaceEngineers" / "Blueprints" / "local" / args.grid / "bp.sbc")
            blueprint_path, temp_dir = resolve_blueprint_path(blueprint_arg)
            tree = parse_blueprint(blueprint_path)
            blueprint_source_description = f"Blueprint file: {blueprint_path}"

        root = tree.getroot()
        cube_grid = get_cube_grid(root)
        cube_blocks = get_cube_blocks(cube_grid)
        grid_step = args.grid_step or grid_step_from_blueprint(cube_grid)

        print(blueprint_source_description)
        print(f"Grid step: {grid_step:g} m")
        print(f"Original blocks: {len(list(cube_blocks))}")

        if args.redis_save_file:
            xml_for_save = finalize_blueprint(root, args.redis_save_file)
            record = redis_save_blueprint_record(
                client_for_redis,
                owner_id_for_redis,
                name=args.redis_save_file,
                xml=xml_for_save,
                source="file",
                grid_name=args.grid,
                grid_id="",
                custom_prefix=args.redis_prefix,
            )
            print(
                f"Saved file blueprint to Redis: name={record['name']}, blocks={record['blockCount']}, "
                f"size={record['xmlSize']}, checksum={record['checksumSha256'][:12]}..."
            )
            return 0

        if args.offline:
            print("Offline mode: Redis/game connection skipped")
        else:
            from secontrol.common import prepare_grid

            grid = prepare_grid(args.grid, auto_wake=True, wake_timeout=args.wake_timeout)
            grid.refresh_devices()
            live_blocks = collect_live_blocks(grid, grid_step)
            live_by_entity_map = live_blocks_by_entity(live_blocks)
            projector = find_projector(grid, args.projector_name, args.projector_subtype)
            live_projector_id = projector_device_id(projector)
            live_projector = live_projector_block_from_device(projector, live_by_entity_map, grid_step)
            live_projector_min = live_projector.min
            print(f"Main grid: {grid.name} ({grid.grid_id})")
            print(f"Live blocks known from telemetry: {len(live_blocks)}")
            print(f"Projector from telemetry: {projector.name} ({live_projector_id or '?'}) at {live_projector_min}; orientation={orientation_to_text(live_projector.orientation_forward, live_projector.orientation_up)}")

            if not args.no_live_blueprint_frame:
                live_blocks, exported_projector, live_frame_message = try_refresh_live_frame_from_projector_export(
                    projector,
                    timeout=args.grid_export_timeout,
                    include_connected=args.live_frame_include_connected,
                    live_projector_id=live_projector_id,
                    telemetry_live_blocks=live_blocks,
                )
                print(live_frame_message)
                live_by_entity_map = live_blocks_by_entity(live_blocks)
                if exported_projector is not None:
                    live_projector = exported_projector
                    live_projector_min = exported_projector.min
            else:
                print("Live blueprint frame export disabled; using telemetry projector frame")

            print(f"Live blocks used for placement: {len(live_blocks)}")
            print(f"Projector frame used: {projector.name} ({live_projector_id or '?'}) at {live_projector_min}; orientation={orientation_to_text(live_projector.orientation_forward, live_projector.orientation_up)}")
            projector_ui_correction = resolve_projector_ui_origin_correction(
                projector,
                args.projector_subtype,
                args.projector_ui_correction,
                args.no_small_projector_correction,
            )
            if projector_ui_correction != Vec3i(0, 0, 0):
                reason = "manual" if args.projector_ui_correction is not None else "auto SmallProjector"
                print(f"Projector UI origin correction: {projector_ui_correction} ({reason})")
            else:
                print("Projector UI origin correction: (0, 0, 0)")

        fixed_projector_element_ids = collect_missing_projector_min_elements(cube_blocks)
        source_first_origin_min, source_first_origin_message = first_preview_block_origin_min(cube_blocks)
        print(f"Game projection origin from source before cleanup: {source_first_origin_min} ({source_first_origin_message})")
        if fixed_projector_element_ids:
            print(
                "Detected projector blocks without Min in source XML: "
                f"{len(fixed_projector_element_ids)}; in native projector mode they must remain without Min "
                "because VRage uses default (0,0,0) as the preview first-block origin"
            )

        filled = fill_missing_min_from_live(cube_blocks, live_by_entity_map)
        if filled:
            print(f"Filled missing Min from live grid: {filled}")

        projector_min_fallback = args.blueprint_projector_min or live_projector_min
        filled_projector = 0
        if args.rotation_mode == "xml":
            filled_projector = fill_missing_projector_min(cube_blocks, projector_min_fallback)
            if filled_projector:
                print(f"Filled missing projector Min from fallback anchor: {filled_projector} at {projector_min_fallback}")
        else:
            print("Native projector mode: preserving missing projector Min; this keeps vanilla first-block origin at default (0,0,0)")

        removed_invalid = remove_blocks_without_min(cube_blocks, preserve_projectors=(args.rotation_mode != "xml"))
        if removed_invalid:
            print("WARNING: removed blocks without Min:")
            for item in removed_invalid:
                print(f"  - {item}")

        strip_xml = args.strip_nonessential
        if strip_xml:
            removed_tags = strip_bloated_block_data(cube_blocks)
            if removed_tags:
                print(f"Stripped non-essential block XML tags: {removed_tags}")
            else:
                print("Stripped non-essential block XML tags: 0")
        else:
            print("Preserving full block XML: enabled")

        blocks = collect_blueprint_blocks(cube_blocks)
        print(f"Usable blocks after cleanup: {len(blocks)}")

        blueprint_pair = choose_blueprint_pair(blocks, args.contact_tag)
        if args.offline:
            live_pair = LiveContactPair(
                merge=LiveBlock(
                    block_type=blueprint_pair.merge.block_type,
                    subtype=blueprint_pair.merge.subtype,
                    entity_id=blueprint_pair.merge.entity_id,
                    name=blueprint_pair.merge.name,
                    min=blueprint_pair.merge.min,
                ),
                connector=LiveBlock(
                    block_type=blueprint_pair.connector.block_type,
                    subtype=blueprint_pair.connector.subtype,
                    entity_id=blueprint_pair.connector.entity_id,
                    name=blueprint_pair.connector.name,
                    min=blueprint_pair.connector.min,
                ),
            )
            live_blocks = [live_pair.merge, live_pair.connector]
        else:
            live_pair = choose_live_pair(live_blocks, blueprint_pair, live_by_entity_map, args.contact_tag)
            if live_pair is None:
                raise RuntimeError("live merge/connector pair was not found from telemetry")

        print(f"Blueprint merge:     {blueprint_pair.merge.subtype} entity={blueprint_pair.merge.entity_id or '?'} at {blueprint_pair.merge.min}")
        print(f"Blueprint connector: {blueprint_pair.connector.subtype} entity={blueprint_pair.connector.entity_id or '?'} at {blueprint_pair.connector.min}")
        print(f"Live merge:          {live_pair.merge.subtype} entity={live_pair.merge.entity_id or '?'} at {live_pair.merge.min}")
        print(f"Live connector:      {live_pair.connector.subtype} entity={live_pair.connector.entity_id or '?'} at {live_pair.connector.min}")

        if (args.projector_forward is None) != (args.projector_up is None):
            raise ValueError("--projector-forward and --projector-up must be provided together")

        projector_to_grid: Rotation = identity_rotation
        grid_to_projector: Rotation = identity_rotation
        orientation_ok = False
        target_contact_vector = live_pair.vector
        if args.ignore_projector_orientation or args.anchor_mode == "grid-origin" or live_projector is None:
            print("Projector orientation compensation: disabled")
        else:
            orientation_forward = args.projector_forward or live_projector.orientation_forward
            orientation_up = args.projector_up or live_projector.orientation_up
            projector_to_grid, grid_to_projector, orientation_ok, orientation_message = projector_axis_transforms(
                orientation_forward,
                orientation_up,
            )
            target_contact_vector = grid_to_projector(live_pair.vector) if orientation_ok else live_pair.vector
            print(f"Live projector orientation: {orientation_to_text(live_projector.orientation_forward, live_projector.orientation_up)}")
            if args.projector_forward is not None and args.projector_up is not None:
                print(f"Manual projector orientation override: {orientation_to_text(args.projector_forward, args.projector_up)}")
            print(f"Projector orientation compensation: {'enabled' if orientation_ok else 'identity fallback'}; {orientation_message}")
            print(f"Prepared contact vector in projector-local cells: {target_contact_vector}")

        if live_projector is not None:
            print_live_contact_debug(
                projector=live_projector,
                live_pair=live_pair,
                projector_to_grid=projector_to_grid,
                grid_to_projector=grid_to_projector,
                grid_step=grid_step,
            )

        preflip = not args.no_preflip
        contact_axis = target_contact_vector.axis_name()
        if contact_axis is None:
            raise ValueError(f"prepared contact pair must be axis-aligned, got vector {target_contact_vector}")

        projection_rotation = Vec3i(0, 0, 0)
        if args.rotation_mode == "xml":
            contact_axis, used_preflip = prepare_blueprint_geometry(
                blocks,
                blueprint_pair,
                live_pair,
                preflip=preflip,
                fixed_projector_element_ids=fixed_projector_element_ids,
                target_contact_vector=target_contact_vector,
            )
            projection_rotation = Vec3i(0, 0, 0)
            print(f"Contact axis: {contact_axis}")
            print(f"Pre-flip around contact line: {used_preflip}")
            print("Rotation mode: xml block transform")
        else:
            desired_rotation_transform = prepared_projection_direction_transform(
                blueprint_pair.vector,
                target_contact_vector,
                preflip=preflip,
            )
            projection_rotation = find_projection_rotation_for_transform(desired_rotation_transform)

            # Tighten the native rotation with the real connector forward vector.
            # The relative merge->connector vector alone can be correct while the
            # projected connector/merge are turned by the wrong face.  The docking
            # contact must be face-to-face: projected connector Forward must point
            # opposite to the live connector Forward.
            live_connector_forward = live_model_face_vector(live_pair.connector, "forward")
            blueprint_connector_forward = block_model_face_vector(blueprint_pair.connector, "forward")
            if live_connector_forward is not None and is_valid_contact_normal(live_connector_forward, live_pair.vector):
                desired_connector_forward = grid_to_projector(-live_connector_forward)
                constrained_rotation = find_projection_rotation_matching_pairs([
                    (blueprint_pair.vector, target_contact_vector),
                    (blueprint_connector_forward, desired_connector_forward),
                ])
                if constrained_rotation is not None:
                    if constrained_rotation != projection_rotation:
                        print(
                            "Native rotation adjusted by connector Forward contact: "
                            f"old={projection_rotation}, new={constrained_rotation}, "
                            f"blueprintConnectorForward={blueprint_connector_forward}, "
                            f"targetProjectedConnectorForward={desired_connector_forward}"
                        )
                    projection_rotation = constrained_rotation
                    desired_rotation_transform = projection_rotation_transform(projection_rotation)
                else:
                    print(
                        "WARNING: no ProjectionRotation satisfies both pair-vector and connector Forward contact; "
                        f"pair {blueprint_pair.vector}->{target_contact_vector}, "
                        f"connectorForward {blueprint_connector_forward}->{desired_connector_forward}. "
                        "Using pair-vector rotation only."
                    )

            print(f"Contact axis: {contact_axis}")
            print(f"Pre-flip around contact line: {preflip}")
            print("Rotation mode: native projector ProjectionRotation; original block coordinates/orientations are preserved")
            print("Native rotation convention: source-code yaw/pitch/roll; ProjectionRotation.X=yaw(Y), Y=pitch(X), Z=roll(Z)")
            print("Native offset convention: ProjectionOffset is subtracted in projector-local axes after native rotation matrix is built")
            print("Forward contact rule: projected Connector Forward must be opposite live Connector Forward")
            print(f"Native rotation transform: {describe_rotation_on_basis(desired_rotation_transform)}")

        if args.manual_rotation is not None:
            projection_rotation = args.manual_rotation
            print(f"Manual ProjectionRotation override: {projection_rotation}")
        else:
            print(f"ProjectionRotation to apply: {projection_rotation}")

        preferred_contact_normal: Optional[Vec3i] = None
        projected_merge_face_for_normal: Optional[Vec3i] = None
        face_rotation_for_debug = projection_rotation_transform(projection_rotation) if args.rotation_mode != "xml" else identity_rotation
        if args.contact_mode != "overlay" and args.normal == "auto":
            # Use the live connector Forward vector as the contact side.  This is
            # the unambiguous docking face of the connector.  The projected
            # connector Forward is constrained above to point back along -normal.
            live_connector_forward_for_normal = live_model_face_vector(live_pair.connector, "forward")
            if live_connector_forward_for_normal is not None and is_valid_contact_normal(live_connector_forward_for_normal, live_pair.vector):
                preferred_contact_normal = live_connector_forward_for_normal
                print(
                    "Auto contact normal: using live Connector Forward; "
                    f"connectorForward={live_connector_forward_for_normal}, contact_normal={preferred_contact_normal}"
                )
            else:
                # Fallback to the old merge-face based side only when connector
                # orientation is unavailable or invalid.
                fallback_face = "forward" if args.merge_mate_face == "auto" else args.merge_mate_face
                if args.rotation_mode == "xml":
                    projected_merge_face_for_normal = projector_to_grid(block_model_face_vector(blueprint_pair.merge, fallback_face))
                else:
                    projected_merge_face_for_normal = projector_to_grid(face_rotation_for_debug(block_model_face_vector(blueprint_pair.merge, fallback_face)))
                preferred_contact_normal = -projected_merge_face_for_normal
                if is_valid_contact_normal(preferred_contact_normal, live_pair.vector):
                    print(
                        "Auto contact normal fallback: using side opposite projected merge face; "
                        f"projected_face={projected_merge_face_for_normal}, contact_normal={preferred_contact_normal}"
                    )
                else:
                    print(
                        "WARNING: neither connector Forward nor projected merge face gives a valid contact normal; "
                        f"projected_face={projected_merge_face_for_normal}, normal={preferred_contact_normal}, "
                        f"contact_vector={live_pair.vector}; falling back to collision-based auto side"
                    )
                    preferred_contact_normal = None

        selected_merge_mate_face = choose_merge_mate_face_for_contact(
            blueprint_pair.merge,
            face_rotation_for_debug,
            projector_to_grid,
            preferred_contact_normal,
            args.merge_mate_face,
        )
        args.merge_mate_face = selected_merge_mate_face

        print("Projected merge model-face candidates after native rotation:")
        for face_name in MERGE_MATE_FACE_CHOICES:
            face_vec = block_model_face_vector(blueprint_pair.merge, face_name)
            projected_face = projector_to_grid(face_rotation_for_debug(face_vec))
            preferred_side = -projected_face
            contact_match = "CONTACT-FACE" if preferred_contact_normal is not None and projected_face == -preferred_contact_normal else ""
            valid = "valid-normal" if is_valid_contact_normal(preferred_side, live_pair.vector) else "invalid/parallel-to-pair"
            print(f"  {face_name:8s}: projected_face={projected_face}, preferred contact_normal={preferred_side} {valid} {contact_match}")
        print(f"Selected merge mating face model axis: {args.merge_mate_face}")

        blueprint_projector = choose_blueprint_projector_block(
            blocks,
            live_projector_id,
            args.blueprint_projector_min,
            live_projector_min,
            blueprint_pair,
        )
        blueprint_projector_min = blueprint_projector.min
        if live_projector_min is None:
            live_projector_min = blueprint_projector_min
        print(f"Blueprint projector anchor: entity={blueprint_projector.entity_id or '?'} at {blueprint_projector_min}")
        print(f"Live projector anchor:      {live_projector_min}")
        print(f"Offset anchor mode:         {args.anchor_mode}")
        if args.anchor_mode == "projector-block":
            print("Projector anchor rule: native projector math uses the first preview block as the effective origin, not the blueprint projector block")

        game_projection_origin_min = blueprint_projector_min
        if args.rotation_mode != "xml":
            game_projection_origin_min = source_first_origin_min
            print(f"Game projection origin from SE source formula: {game_projection_origin_min} ({source_first_origin_message})")
            if game_projection_origin_min != blueprint_projector_min:
                print(
                    "NOTE: this differs from the blueprint projector anchor; vanilla MyProjectorClipboard "
                    "recenters the preview using PreviewGrids[0].CubeBlocks.First(). Do not fill missing "
                    "SmallProjector Min with the live projector cell in native mode."
                )

        projection_math_anchor_min = game_projection_origin_min if args.rotation_mode != "xml" else blueprint_projector_min
        if projection_math_anchor_min != blueprint_projector_min:
            print(f"Projection math anchor used for native SE formula: {projection_math_anchor_min}")

        if args.rotation_mode == "xml":
            placement = choose_placement(
                blocks,
                live_blocks,
                blueprint_pair,
                live_pair,
                blueprint_projector_min,
                live_projector_min,
                contact_mode=args.contact_mode,
                contact_gap=args.contact_gap,
                normal_text=args.normal,
                anchor_mode=args.anchor_mode,
                projector_to_grid=projector_to_grid,
                grid_to_projector=grid_to_projector,
                preferred_normal=preferred_contact_normal,
            )
        else:
            placement = choose_placement_projector_rotation(
                blocks,
                live_blocks,
                blueprint_pair,
                live_pair,
                game_projection_origin_min,
                live_projector_min,
                projection_rotation,
                contact_mode=args.contact_mode,
                contact_gap=args.contact_gap,
                normal_text=args.normal,
                anchor_mode=args.anchor_mode,
                projector_to_grid=projector_to_grid,
                grid_to_projector=grid_to_projector,
                preferred_normal=preferred_contact_normal,
            )
        print(f"Placement mode: {args.contact_mode}")
        print(f"Contact normal: {placement.normal}")
        print(f"Target merge:   {placement.target_merge}")
        print(f"Target connector:{placement.target_connector}")
        if args.manual_offset is not None:
            placement = PlacementCandidate(
                normal=placement.normal,
                target_merge=placement.target_merge,
                target_connector=placement.target_connector,
                offset=args.manual_offset,
                collisions=placement.collisions,
                predicted_center_score=placement.predicted_center_score,
            )
            print(f"Manual ProjectionOffset override: {placement.offset}")
        else:
            print(f"ProjectionOffset to apply: {placement.offset}")
        print(f"Predicted live-grid collisions by Min cells: {placement.collisions}")

        display_name = args.display_name or f"{Path(blueprint_arg).stem}-contact-clone-offset"

        if args.placement_apply == "xml" and args.rotation_mode != "xml" and args.manual_offset is None:
            raise ValueError("--placement-apply=xml requires --rotation-mode=xml because the final contact shift is baked into block Min coordinates")

        if args.placement_apply == "xml" and args.manual_offset is None:
            # Correct path for cloning next to the current ship:
            #
            # Space Engineers does not respect an absolute translation of the whole blueprint:
            # if every block including the blueprint projector is shifted, the projection stays
            # in the same place relative to the live projector. This is why v13 still overlapped
            # the main ship even though the XML Min cells looked shifted.
            #
            # Therefore we bake the already calculated projector-block offset into the relative
            # geometry: keep the anchor projector block fixed and move the rest of the projected
            # ship by placement.offset. This produces the same mathematical target as a perfect
            # ProjectionOffset, but without relying on the projector UI axes.
            baked_relative_shift = placement.offset
            if args.anchor_mode != "projector-block":
                # In non-projector anchor modes placement.offset is not a relative ship shift.
                # Fall back to the old direct contact delta only for explicit diagnostics.
                baked_relative_shift = placement.target_merge - blueprint_pair.merge.min

            expected_merge_after_bake = predicted_position(
                live_projector_min,
                blueprint_projector_min,
                blueprint_pair.merge.min + baked_relative_shift,
                Vec3i(0, 0, 0),
                args.anchor_mode,
                projector_to_grid,
            )
            expected_connector_after_bake = predicted_position(
                live_projector_min,
                blueprint_projector_min,
                blueprint_pair.connector.min + baked_relative_shift,
                Vec3i(0, 0, 0),
                args.anchor_mode,
                projector_to_grid,
            )
            if expected_merge_after_bake != placement.target_merge:
                raise RuntimeError(
                    "internal XML relative shift error: merge would not reach target; "
                    f"predicted={expected_merge_after_bake}, target={placement.target_merge}"
                )
            if expected_connector_after_bake != placement.target_connector:
                raise RuntimeError(
                    "internal XML relative shift error: connector would not reach target; "
                    f"predicted={expected_connector_after_bake}, target={placement.target_connector}"
                )

            moved_blocks = shift_blueprint_blocks(
                blocks,
                baked_relative_shift,
                skip_anchor_projector=blueprint_projector if args.anchor_mode == "projector-block" else None,
            )
            print(f"XML relative shift applied to non-anchor blocks: {baked_relative_shift}")
            print(f"XML shifted blocks: {moved_blocks}; anchor projector kept at {blueprint_projector.min}")
            print(f"Projected merge after XML relative shift:     {expected_merge_after_bake}")
            print(f"Projected connector after XML relative shift: {expected_connector_after_bake}")
            projected_collisions = count_projected_min_cell_collisions(
                blocks,
                live_blocks,
                live_projector_min,
                blueprint_projector_min,
                Vec3i(0, 0, 0),
                args.anchor_mode,
                projector_to_grid,
            )
            print(f"Predicted live-grid collisions after XML relative shift by projected Min cells: {projected_collisions}")
            projector_offset = projector_ui_correction
            if projector_offset == Vec3i(0, 0, 0):
                print("Placement is baked into XML relative to the anchor projector; projector UI offset is kept at zero")
            else:
                print("Placement is baked into XML relative to the anchor projector")
                print(f"Projector UI offset kept for model-origin correction: {projector_offset}")
        else:
            desired_grid_offset = placement.offset
            projector_offset = desired_grid_offset

            if args.manual_offset is None and not args.offline and not args.no_upload and not args.no_calibrate_offset_axes:
                embedded_count = embed_projector_transform(blocks, Vec3i(0, 0, 0), projection_rotation)
                if embedded_count:
                    print(f"Embedded calibration projector transform into XML blocks: {embedded_count}, offset=(0, 0, 0), rotation={projection_rotation}")
                calibration_xml = finalize_blueprint(root, f"{display_name}-calibration")
                calibrated = calibrate_projector_offset_axes(
                    projector,
                    calibration_xml,
                    desired_grid_offset,
                    projection_rotation,
                    wait_after_load=args.wait,
                    wait_timeout=args.offset_wait,
                    skip_reset=args.skip_reset,
                )
                if calibrated is not None:
                    projector_offset = calibrated
                else:
                    print(f"WARNING: using uncalibrated projector offset: {projector_offset}")
            else:
                if args.no_calibrate_offset_axes:
                    print("Projector offset-axis calibration disabled by argument")
                print(f"Projector UI offset to apply before origin correction: {projector_offset}")

            if projector_ui_correction != Vec3i(0, 0, 0):
                correction_space = args.projector_ui_correction_space
                if correction_space == "auto":
                    # Native ProjectionRotation keeps the original blueprint geometry.
                    # The small-projector UI origin correction was only needed for the
                    # legacy XML-baked mode where the ship was moved relative to a
                    # synthetic projector anchor.  Applying it after native placement
                    # moves the already-correct merge/connector target away from the
                    # calculated contact point.
                    correction_space = "none" if args.rotation_mode == "projector" else "ui"

                if correction_space == "none":
                    print(f"Projector UI origin correction ignored by mode: base={projector_ui_correction}")
                else:
                    correction_to_apply = projector_ui_correction
                    if correction_space == "rotated":
                        correction_to_apply = projection_rotation_transform(projection_rotation)(projector_ui_correction)
                        print(f"Projector UI origin correction rotated by ProjectionRotation: base={projector_ui_correction}, applied={correction_to_apply}")
                    else:
                        print(f"Projector UI origin correction applied in raw UI axes: {correction_to_apply}")
                    projector_offset = add_vec3i(projector_offset, correction_to_apply)
                    print(f"Projector UI offset after origin correction: {projector_offset}")

        if args.rotation_mode != "xml" and projection_math_anchor_min != blueprint_projector_min:
            print(f"Final prediction uses SE first-block anchor {projection_math_anchor_min}, not blueprint projector anchor {blueprint_projector_min}")

        if args.rotation_mode == "projector":
            final_rotation_transform = projection_rotation_transform(projection_rotation)
            final_merge = predicted_position_with_rotation(
                live_projector_min,
                projection_math_anchor_min,
                blueprint_pair.merge.min,
                projector_offset,
                final_rotation_transform,
                args.anchor_mode,
                projector_to_grid,
            )
            final_connector = predicted_position_with_rotation(
                live_projector_min,
                projection_math_anchor_min,
                blueprint_pair.connector.min,
                projector_offset,
                final_rotation_transform,
                args.anchor_mode,
                projector_to_grid,
            )
        else:
            final_merge = predicted_position(
                live_projector_min,
                projection_math_anchor_min,
                blueprint_pair.merge.min,
                projector_offset,
                args.anchor_mode,
                projector_to_grid,
            )
            final_connector = predicted_position(
                live_projector_min,
                projection_math_anchor_min,
                blueprint_pair.connector.min,
                projector_offset,
                args.anchor_mode,
                projector_to_grid,
            )

        if args.rotation_mode == "projector":
            final_projected_merge_face = projector_to_grid(final_rotation_transform(block_model_face_vector(blueprint_pair.merge, args.merge_mate_face)))
        else:
            final_projected_merge_face = projector_to_grid(block_model_face_vector(blueprint_pair.merge, args.merge_mate_face))

        print(f"Final predicted merge with embedded transform:     {final_merge}")
        print(f"Final predicted connector with embedded transform: {final_connector}")
        print(f"Final projected merge face direction:              {final_projected_merge_face}")
        if live_projector is not None:
            print_projection_contact_debug(
                live_projector=live_projector,
                blueprint_projector_min=projection_math_anchor_min,
                blueprint_pair=blueprint_pair,
                live_pair=live_pair,
                projector_offset=projector_offset,
                projection_rotation=projection_rotation,
                final_merge=final_merge,
                final_connector=final_connector,
                final_projected_merge_face=final_projected_merge_face,
                grid_step=grid_step,
            )
            print_projection_transform_audit(
                live_projector=live_projector,
                blueprint_projector_min=projection_math_anchor_min,
                blueprint_pair=blueprint_pair,
                live_pair=live_pair,
                offset=projector_offset,
                rotation=projection_rotation,
                projector_to_grid=projector_to_grid,
                grid_step=grid_step,
            )
        if final_merge != placement.target_merge or final_connector != placement.target_connector:
            print(
                "WARNING: final embedded projector transform does not match the requested contact targets; "
                f"merge target={placement.target_merge}, connector target={placement.target_connector}"
            )

        if args.verify_contact == "on":
            contact_ok = contact_alignment_report(
                final_merge=final_merge,
                final_connector=final_connector,
                projected_merge_face=final_projected_merge_face,
                live_pair=live_pair,
                placement=placement,
                contact_gap=args.contact_gap,
            )
            if args.strict_contact_verify and not contact_ok:
                print("ERROR: strict contact verification failed; upload skipped", file=sys.stderr)
                return 2

        embedded_count = embed_projector_transform(blocks, projector_offset, projection_rotation)
        if embedded_count:
            print(f"Embedded final projector transform into XML blocks: {embedded_count}, offset={projector_offset}, rotation={projection_rotation}")
        else:
            print("WARNING: no projector block found in prepared XML; final offset/rotation can only be applied after load")

        if args.drop_synthetic_projector_blocks and fixed_projector_element_ids:
            dropped = 0
            for element in list(cube_blocks):
                if id(element) in fixed_projector_element_ids:
                    cube_blocks.remove(element)
                    dropped += 1
            if dropped:
                blocks = [block for block in blocks if id(block.element) not in fixed_projector_element_ids]
            print(f"Dropped synthetic projector anchor blocks from final XML: {dropped}")

        final_block_count = len(list(cube_blocks))
        print(f"Final CubeBlocks in prepared XML: {final_block_count}")

        xml = finalize_blueprint(root, display_name)
        if "<MyObjectBuilder_ShipBlueprintDefinition" not in xml:
            raise RuntimeError("generated XML does not contain MyObjectBuilder_ShipBlueprintDefinition")

        output_path = Path(args.output).expanduser().resolve() if args.output else Path.cwd() / f"{display_name}.sbc"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml, encoding="utf-8")
        print(f"Prepared blueprint saved: {output_path}")
        print(f"Prepared XML size: {len(xml)} chars")

        if args.no_upload or args.offline:
            print("Upload skipped")
            return 0

        if grid is None or projector is None:
            raise RuntimeError("grid/projector connection is not available")

        if not args.skip_clear_existing:
            clear_existing_projector_blueprint(projector, wait_timeout=args.clear_timeout)
        elif not args.skip_reset:
            try:
                projector.reset_projection()
                time.sleep(0.5)
            except Exception as exc:
                print(f"WARNING: reset_projection failed: {exc}")

        projector.set_enabled(True)
        seq_id = projector.load_blueprint_xml(xml, keep=args.keep)
        print(f"load_blueprint_xml sent: seq_id={seq_id}")
        time.sleep(args.wait)
        runtime_mode = args.runtime_transform_mode
        if runtime_mode == "auto":
            runtime_mode = "none" if embedded_count > 0 else "apply"
        if runtime_mode == "apply":
            print("Runtime projector transform apply: enabled")
            apply_projector_transform(projector, projector_offset, projection_rotation, args.offset_wait)
        else:
            print(
                "Runtime projector transform apply: skipped; "
                "offset/rotation are embedded into the loaded XML, so set_rotation/set_offset are not sent again"
            )

        if args.projection_probe:
            probe_candidates = build_projection_probe_candidates(
                live_projector_min=live_projector_min,
                blueprint_projector_min=projection_math_anchor_min,
                blueprint_pair=blueprint_pair,
                live_pair=live_pair,
                base_offset=projector_offset,
                base_rotation=projection_rotation,
                base_normal=placement.normal,
                anchor_mode=args.anchor_mode,
                contact_gap=args.contact_gap,
                projector_to_grid=projector_to_grid,
                grid_to_projector=grid_to_projector,
                radius=args.projection_probe_radius,
                rotation_mode=args.projection_probe_rotations,
                normal_mode=args.projection_probe_normals,
                limit=args.projection_probe_max_candidates,
            )
            probe_report = {}
            if args.projection_probe_mode in ("auto", "plugin"):
                probe_report = run_projection_probe(
                    projector,
                    probe_candidates,
                    wait=args.projection_probe_wait,
                    apply_best=not args.no_projection_probe_apply_best,
                    max_candidates=args.projection_probe_max_candidates,
                )
            if args.projection_probe_mode == "client" or (args.projection_probe_mode == "auto" and not probe_report):
                if args.projection_probe_mode == "auto":
                    print("Projection probe: falling back to Python client-side probing using live telemetry")
                probe_report = run_client_side_projection_probe(
                    projector,
                    probe_candidates,
                    wait_per_candidate=args.projection_probe_client_wait,
                    settle_after_match=args.projection_probe_client_settle,
                    apply_best=not args.no_projection_probe_apply_best,
                    max_candidates=args.projection_probe_max_candidates,
                    merge_entity_id=blueprint_pair.merge.entity_id,
                    connector_entity_id=blueprint_pair.connector.entity_id,
                )
            if probe_report:
                try:
                    report_path = Path(output_path).with_suffix(".projection-probe-report.json")
                    report_path.write_text(json.dumps(probe_report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"Projection probe raw report saved: {report_path}")
                except Exception as exc:
                    print(f"WARNING: failed to save projection probe report: {exc}")
        time.sleep(0.5)
        try:
            projector.update()
        except Exception:
            pass
        time.sleep(0.25)
        telemetry = read_projector_telemetry_raw(projector)
        print("Projector telemetry:")
        print(f"  isProjecting:    {bool_from_telemetry(telemetry.get('isProjecting'))}")
        print(f"  projectedGrid:   {bool_from_telemetry(telemetry.get('projectedGridName'))}")
        print(f"  offset:          {bool_from_telemetry(telemetry.get('offset'))}")
        print(f"  rotation:        {bool_from_telemetry(telemetry.get('rotation'))}")
        print(f"  totalBlocks:     {bool_from_telemetry(telemetry.get('totalBlocks'))}")
        print(f"  remainingBlocks: {bool_from_telemetry(telemetry.get('remainingBlocks'))}")
        print(f"  buildableBlocks: {bool_from_telemetry(telemetry.get('buildableBlocks'))}")
        if not args.no_projection_report_after_load:
            report_output = Path(args.projection_report_output).expanduser().resolve() if args.projection_report_output else output_path.with_suffix(".projection-report.json")
            scan_projection_contact_report(
                projector,
                wait=args.projection_report_wait,
                max_blocks=args.projection_report_max_blocks,
                merge_entity_id=blueprint_pair.merge.entity_id,
                connector_entity_id=blueprint_pair.connector.entity_id,
                output_path=report_output,
            )
        print("Projection loaded, projector enabled, offset applied.")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if grid is not None:
            try:
                from secontrol.common import close
                close(grid)
            except Exception:
                pass
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
