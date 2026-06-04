#!/usr/bin/env python3
"""Load a transformed clone blueprint into a Space Engineers projector.

The script is designed for autonomous agents that need a repeatable way to
place a clone projection at a docking/build contact point. The contact point is
identified by a Merge Block and a Connector. By default the blueprint is rotated
180 degrees around the contact line so the projected ship grows on the opposite
side while the Merge Block and Connector stay exactly on the main ship contact
blocks.
"""

from __future__ import annotations

import argparse
import copy
import math
import shutil
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from itertools import permutations, product
from pathlib import Path
from typing import Callable, Iterable, Optional, TypeVar
import xml.etree.ElementTree as ET


XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
ET.register_namespace("xsi", XSI_NS)
ET.register_namespace("xsd", XSD_NS)

DIRECTION_TO_VEC: dict[str, tuple[int, int, int]] = {
    "Right": (1, 0, 0),
    "Left": (-1, 0, 0),
    "Up": (0, 1, 0),
    "Down": (0, -1, 0),
    "Backward": (0, 0, 1),
    "Forward": (0, 0, -1),
}
VEC_TO_DIRECTION = {value: key for key, value in DIRECTION_TO_VEC.items()}

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

    def __neg__(self) -> "Vec3i":
        return Vec3i(-self.x, -self.y, -self.z)

    def as_tuple(self) -> tuple[int, int, int]:
        return self.x, self.y, self.z

    def manhattan(self) -> int:
        return abs(self.x) + abs(self.y) + abs(self.z)

    def axis_name(self) -> Optional[str]:
        nonzero = [("x", self.x), ("y", self.y), ("z", self.z)]
        active = [(name, value) for name, value in nonzero if value != 0]
        if len(active) != 1:
            return None
        return active[0][0]


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


@dataclass(frozen=True)
class LiveContactPair:
    merge: LiveBlock
    connector: LiveBlock

    @property
    def vector(self) -> Vec3i:
        return self.connector.min - self.merge.min


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


def parse_blueprint(path: Path) -> ET.ElementTree:
    data = path.read_text(encoding="utf-8-sig", errors="replace")
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


def live_blocks_by_entity(grid: object, grid_step: float) -> dict[int, LiveBlock]:
    result: dict[int, LiveBlock] = {}
    for block in getattr(grid, "iter_blocks")():
        entity_id = getattr(block, "block_id", None)
        local_position = getattr(block, "local_position", None)
        if entity_id is None or not local_position or len(local_position) < 3:
            continue
        min_pos = Vec3i(
            int(round(float(local_position[0]) / grid_step)),
            int(round(float(local_position[1]) / grid_step)),
            int(round(float(local_position[2]) / grid_step)),
        )
        result[int(entity_id)] = LiveBlock(
            block_type=str(getattr(block, "block_type", "") or ""),
            subtype=str(getattr(block, "subtype", "") or ""),
            entity_id=int(entity_id),
            name=str(getattr(block, "name", "") or ""),
            min=min_pos,
        )
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


def remove_blocks_without_min(cube_blocks: ET.Element) -> list[str]:
    removed: list[str] = []
    for block in list(cube_blocks):
        if read_min(block) is not None:
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


def filter_by_tag(items: Iterable[T], tag: str, text_getter: Callable[[T], str]) -> list[T]:
    if not tag:
        return list(items)
    needle = tag.lower()
    return [item for item in items if needle in text_getter(item).lower()]


def choose_blueprint_pair(blocks: list[BlueprintBlock], tag: str = "") -> ContactPair:
    merges = [block for block in blocks if is_merge_type(block.block_type, block.subtype)]
    connectors = [block for block in blocks if is_connector_type(block.block_type, block.subtype)]
    merges = filter_by_tag(merges, tag, lambda b: f"{b.name} {b.subtype} {b.block_type}")
    connectors = filter_by_tag(connectors, tag, lambda b: f"{b.name} {b.subtype} {b.block_type}")
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


def choose_live_pair(grid: object, grid_step: float, tag: str = "") -> Optional[LiveContactPair]:
    live_blocks: list[LiveBlock] = []
    for block in getattr(grid, "iter_blocks")():
        local_position = getattr(block, "local_position", None)
        if not local_position or len(local_position) < 3:
            continue
        entity_id = getattr(block, "block_id", None)
        live_blocks.append(
            LiveBlock(
                block_type=str(getattr(block, "block_type", "") or ""),
                subtype=str(getattr(block, "subtype", "") or ""),
                entity_id=int(entity_id) if entity_id is not None else None,
                name=str(getattr(block, "name", "") or ""),
                min=Vec3i(
                    int(round(float(local_position[0]) / grid_step)),
                    int(round(float(local_position[1]) / grid_step)),
                    int(round(float(local_position[2]) / grid_step)),
                ),
            )
        )

    merges = [block for block in live_blocks if is_merge_type(block.block_type, block.subtype)]
    connectors = [block for block in live_blocks if is_connector_type(block.block_type, block.subtype)]
    merges = filter_by_tag(merges, tag, lambda b: f"{b.name} {b.subtype} {b.block_type}")
    connectors = filter_by_tag(connectors, tag, lambda b: f"{b.name} {b.subtype} {b.block_type}")
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


def transform_blueprint(
    blocks: list[BlueprintBlock],
    blueprint_pair: ContactPair,
    live_pair: LiveContactPair,
    *,
    mirror_over_contact_line: bool,
) -> tuple[Vec3i, str, bool]:
    base_rotation = choose_base_rotation(blueprint_pair.vector, live_pair.vector)
    contact_axis = live_pair.vector.axis_name()
    if contact_axis is None:
        raise ValueError(f"live contact pair must be axis-aligned, got vector {live_pair.vector}")

    mirror_position_rotation = rotate_180_around_axis(contact_axis, live_pair.merge.min)
    mirror_direction_rotation = rotate_180_direction_around_axis(contact_axis)

    def position_transform(position: Vec3i) -> Vec3i:
        local = position - blueprint_pair.merge.min
        rotated = base_rotation(local)
        placed = live_pair.merge.min + rotated
        if mirror_over_contact_line:
            return mirror_position_rotation(placed)
        return placed

    def direction_transform(direction: Vec3i) -> Vec3i:
        rotated = base_rotation(direction)
        if mirror_over_contact_line:
            return mirror_direction_rotation(rotated)
        return rotated

    for block in blocks:
        new_min = position_transform(block.min)
        set_min(block.element, new_min)
        update_orientation(block.element, direction_transform)
        if is_projector_type(block.block_type, block.subtype):
            ensure_projection_vector(block.element, "ProjectionOffset", Vec3i(0, 0, 0))
            ensure_projection_vector(block.element, "ProjectionRotation", Vec3i(0, 0, 0))

    transformed_merge = position_transform(blueprint_pair.merge.min)
    transformed_connector = position_transform(blueprint_pair.connector.min)
    if transformed_merge != live_pair.merge.min or transformed_connector != live_pair.connector.min:
        raise RuntimeError(
            "internal transform error: contact pair does not align after transform; "
            f"merge={transformed_merge}/{live_pair.merge.min}, "
            f"connector={transformed_connector}/{live_pair.connector.min}"
        )

    translation = live_pair.merge.min - base_rotation(blueprint_pair.merge.min)
    return translation, contact_axis, mirror_over_contact_line


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
    return '<?xml version="1.0" encoding="utf-16"?>\n' + xml_body


def find_projector(grid: object, name_filter: str = "") -> object:
    projectors = list(getattr(grid, "find_devices_by_type")("projector"))
    if name_filter:
        needle = name_filter.lower()
        projectors = [projector for projector in projectors if needle in str(projector.name or "").lower()]
    if not projectors:
        suffix = f" with name containing '{name_filter}'" if name_filter else ""
        raise RuntimeError(f"projector{suffix} not found on grid {getattr(grid, 'name', '?')}")
    return projectors[0]


def bool_from_telemetry(value: object) -> str:
    if value is None:
        return "?"
    return str(value)


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transform a Space Engineers blueprint clone to a merge/connector contact point and load it into a projector.",
    )
    parser.add_argument("grid", help="Main grid name or id, for example skynet-agent0")
    parser.add_argument("blueprint", help="Path to bp.sbc, blueprint directory, or zip that contains bp.sbc")
    parser.add_argument("--output", default="", help="Write transformed XML to this file")
    parser.add_argument("--contact-tag", default="", help="Prefer merge/connector blocks whose name/type/subtype contains this text")
    parser.add_argument("--projector-name", default="", help="Use projector whose name contains this text")
    parser.add_argument("--display-name", default="", help="Display name for the temporary transformed blueprint")
    parser.add_argument("--grid-step", type=positive_float, default=0.0, help="Override block size in meters: 2.5 for large grid, 0.5 for small grid")
    parser.add_argument("--no-mirror", action="store_true", help="Only translate/rotate contact pair; do not flip the clone over the contact line")
    parser.add_argument("--no-upload", action="store_true", help="Only generate/check transformed XML; do not call projector.load_blueprint_xml")
    parser.add_argument("--offline", action="store_true", help="Do not connect to Redis/game; use blueprint contact pair as the live target and skip upload")
    parser.add_argument("--keep", action="store_true", help="Pass keep=True to load_blueprint_xml")
    parser.add_argument("--wait", type=positive_float, default=2.0, help="Seconds to wait after load before telemetry check")
    parser.add_argument("--wake-timeout", type=positive_float, default=3.0, help="Seconds to wait while waking the grid")
    parser.add_argument("--skip-reset", action="store_true", help="Do not call reset_projection before loading")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    grid = None

    try:
        blueprint_path, temp_dir = resolve_blueprint_path(args.blueprint)
        tree = parse_blueprint(blueprint_path)
        root = tree.getroot()
        cube_grid = get_cube_grid(root)
        cube_blocks = get_cube_blocks(cube_grid)
        grid_step = args.grid_step or grid_step_from_blueprint(cube_grid)

        print(f"Blueprint file: {blueprint_path}")
        print(f"Grid step: {grid_step:g} m")
        print(f"Original blocks: {len(list(cube_blocks))}")

        live_by_entity: dict[int, LiveBlock] = {}
        if args.offline:
            print("Offline mode: Redis/game connection skipped")
        else:
            from secontrol.common import close, prepare_grid

            grid = prepare_grid(args.grid, auto_wake=True, wake_timeout=args.wake_timeout)
            grid.refresh_devices()
            print(f"Main grid: {grid.name} ({grid.grid_id})")
            print(f"Live blocks known: {len(list(grid.iter_blocks()))}")
            live_by_entity = live_blocks_by_entity(grid, grid_step)

        filled = fill_missing_min_from_live(cube_blocks, live_by_entity)
        if filled:
            print(f"Filled missing Min from live grid: {filled}")

        removed_invalid = remove_blocks_without_min(cube_blocks)
        if removed_invalid:
            print("WARNING: removed blocks without Min:")
            for item in removed_invalid:
                print(f"  - {item}")

        removed_tags = strip_bloated_block_data(cube_blocks)
        if removed_tags:
            print(f"Stripped non-essential block XML tags: {removed_tags}")

        blocks = collect_blueprint_blocks(cube_blocks)
        print(f"Usable blocks after cleanup: {len(blocks)}")

        blueprint_pair = choose_blueprint_pair(blocks, args.contact_tag)
        live_pair = None if args.offline or grid is None else choose_live_pair(grid, grid_step, args.contact_tag)
        if live_pair is None:
            print("WARNING: live merge/connector pair was not found from telemetry; using blueprint pair as live target")
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

        print(f"Blueprint merge:    {blueprint_pair.merge.subtype} at {blueprint_pair.merge.min}")
        print(f"Blueprint connector:{blueprint_pair.connector.subtype} at {blueprint_pair.connector.min}")
        print(f"Live merge:         {live_pair.merge.subtype} at {live_pair.merge.min}")
        print(f"Live connector:     {live_pair.connector.subtype} at {live_pair.connector.min}")

        translation, axis, mirrored = transform_blueprint(
            blocks,
            blueprint_pair,
            live_pair,
            mirror_over_contact_line=not args.no_mirror,
        )
        print(f"Contact axis: {axis}")
        print(f"Base translation: {translation}")
        print(f"Mirror over contact line: {mirrored}")

        display_name = args.display_name or f"{Path(args.blueprint).stem}-contact-clone"
        xml = finalize_blueprint(root, display_name)
        if "<MyObjectBuilder_ShipBlueprintDefinition" not in xml:
            raise RuntimeError("generated XML does not contain MyObjectBuilder_ShipBlueprintDefinition")

        output_path = Path(args.output).expanduser().resolve() if args.output else Path.cwd() / f"{display_name}.sbc"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml, encoding="utf-8")
        print(f"Transformed blueprint saved: {output_path}")
        print(f"Transformed XML size: {len(xml)} chars")

        if args.no_upload or args.offline:
            print("Upload skipped")
            return 0

        if grid is None:
            raise RuntimeError("grid connection is not available")

        projector = find_projector(grid, args.projector_name)
        print(f"Projector: {projector.name} ({projector.metadata.device_id})")
        if not args.skip_reset:
            try:
                projector.reset_projection()
                time.sleep(0.5)
            except Exception as exc:
                print(f"WARNING: reset_projection failed: {exc}")

        projector.set_enabled(True)
        seq_id = projector.load_blueprint_xml(xml, keep=args.keep)
        print(f"load_blueprint_xml sent: seq_id={seq_id}")
        time.sleep(args.wait)
        projector.update()
        telemetry = projector.telemetry or {}
        print("Projector telemetry:")
        print(f"  isProjecting:    {bool_from_telemetry(telemetry.get('isProjecting'))}")
        print(f"  projectedGrid:   {bool_from_telemetry(telemetry.get('projectedGridName'))}")
        print(f"  totalBlocks:     {bool_from_telemetry(telemetry.get('totalBlocks'))}")
        print(f"  remainingBlocks: {bool_from_telemetry(telemetry.get('remainingBlocks'))}")
        print(f"  buildableBlocks: {bool_from_telemetry(telemetry.get('buildableBlocks'))}")
        print("Projection loaded and projector enabled.")
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
