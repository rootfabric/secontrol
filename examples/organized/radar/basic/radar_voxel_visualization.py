"""
Example of using RadarController to scan voxels and visualize them.

Solid voxel rendering is intentionally limited to the outer envelope only:
internal voxel cells are not converted to PyVista geometry. Ores are not
filtered and are rendered with distinct colors and labels.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pyvista as pv

from secontrol.common import close, prepare_grid
from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.tools.navigation_tools import get_world_position


SCRIPT_VERSION = "radar-voxel-wire-lines-v7-2026-06-06"

# Solid voxel layer settings.
# Draw solid voxels only as gray wire lines, without filled gray panels.
# The outer-envelope filtering is kept, so the whole internal voxel mass is not rendered.
SOLID_LINE_OPACITY = 0.35
SOLID_LINE_WIDTH = 1.0

# ── Ore color map, copied from radar_ore_then_voxels.py ──────────────────
ORE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "Iron": (180, 100, 60),
    "Nickel": (120, 170, 80),
    "Cobalt": (60, 140, 200),
    "Magnesium": (220, 220, 220),
    "Silicon": (200, 190, 140),
    "Silver": (190, 190, 210),
    "Gold": (255, 215, 0),
    "Platinum": (180, 220, 240),
    "Uranium": (80, 220, 80),
    "Uraninite": (80, 220, 80),
    "Ice": (140, 200, 255),
    "Stone": (128, 128, 128),
}
DEFAULT_ORE_COLOR: Tuple[int, int, int] = (200, 80, 200)

last_scan_signature: Optional[Tuple[Any, ...]] = None


def ore_color(name: str) -> Tuple[int, int, int]:
    """Return RGB tuple for an ore name."""
    normalized = str(name or "")
    for key, rgb in ORE_COLORS.items():
        if key.lower() in normalized.lower():
            return rgb
    return DEFAULT_ORE_COLOR


def as_point(value: Any) -> Optional[List[float]]:
    """Return [x, y, z] from list/tuple or dict point forms."""
    if isinstance(value, dict):
        try:
            return [float(value["x"]), float(value["y"]), float(value["z"])]
        except (KeyError, TypeError, ValueError):
            return None

    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return [float(value[0]), float(value[1]), float(value[2])]
        except (TypeError, ValueError):
            return None

    return None


def point_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def ore_name(cell: Dict[str, Any]) -> str:
    """Return ore/material name from the common radar ore cell formats."""
    return str(
        cell.get("ore")
        or cell.get("material")
        or cell.get("subtype")
        or cell.get("type")
        or "Unknown"
    )


def ore_position(cell: Dict[str, Any]) -> Optional[List[float]]:
    """Return ore cell position from all known radar formats."""
    pos = as_point(cell.get("position") or cell.get("pos") or cell.get("center"))
    if pos:
        return pos

    for x_key, y_key, z_key in (("centerX", "centerY", "centerZ"), ("x", "y", "z")):
        if x_key in cell and y_key in cell and z_key in cell:
            try:
                return [float(cell[x_key]), float(cell[y_key]), float(cell[z_key])]
            except (TypeError, ValueError):
                return None

    return None


def ore_content(cell: Dict[str, Any]) -> str:
    value = cell.get("content")
    if value is None:
        value = cell.get("amount")
    if value is None:
        value = cell.get("value")
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def contact_position(contact: Dict[str, Any]) -> Optional[List[float]]:
    """Return contact position as [x, y, z]."""
    return as_point(contact.get("position") or contact.get("pos") or contact.get("center"))


def contact_label(contact: Dict[str, Any], fallback: str) -> str:
    for key in ("name", "displayName", "playerName", "gridName", "id", "ownerId"):
        value = contact.get(key)
        if value not in (None, ""):
            return f"{fallback}: {value}"
    return fallback


def extract_solid(
    radar: Dict[str, Any],
) -> Tuple[List[List[float]], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract solid points, metadata, contacts, and ore cells from radar data."""
    raw = radar.get("raw", {})
    if not isinstance(raw, dict):
        raw = {}

    solid = raw.get("solidPoints", [])
    if not isinstance(solid, list):
        solid = []

    metadata = {
        "size": raw.get("size", [100, 100, 100]),
        "cellSize": raw.get("cellSize", 1.0),
        "origin": raw.get("origin", [0.0, 0.0, 0.0]),
        "rev": raw.get("rev", 0),
    }

    contacts = radar.get("contacts", [])
    if not isinstance(contacts, list):
        contacts = []

    ore_cells = radar.get("oreCells", [])
    if not isinstance(ore_cells, list):
        ore_cells = []

    return solid, metadata, contacts, ore_cells


def get_own_position(grid) -> Optional[List[float]]:
    """Get own world position from cockpit or remote control."""
    for device_type in ("cockpit", "remote_control"):
        devices = grid.find_devices_by_type(device_type)
        if not devices:
            continue

        device = devices[0]
        device.update()
        position = get_world_position(device)
        if position:
            return [float(position[0]), float(position[1]), float(position[2])]

    return None


def normalize_metadata(metadata: Dict[str, Any]) -> Tuple[Tuple[int, int, int], np.ndarray, float]:
    size_raw = metadata.get("size") or [100, 100, 100]
    if not isinstance(size_raw, (list, tuple)) or len(size_raw) < 3:
        size_raw = [100, 100, 100]

    size = (
        max(1, int(size_raw[0])),
        max(1, int(size_raw[1])),
        max(1, int(size_raw[2])),
    )

    origin_raw = metadata.get("origin") or [0.0, 0.0, 0.0]
    if not isinstance(origin_raw, (list, tuple)) or len(origin_raw) < 3:
        origin_raw = [0.0, 0.0, 0.0]
    origin = np.array(origin_raw[:3], dtype=float)

    cell_size = float(metadata.get("cellSize") or 1.0)
    if cell_size <= 0:
        cell_size = 1.0

    return size, origin, cell_size


def build_occ_grid(solid: Iterable[Sequence[float]], metadata: Dict[str, Any]) -> Optional[np.ndarray]:
    """Convert solid world points to a boolean occupancy grid."""
    solid_list = list(solid or [])
    if not solid_list:
        return None

    (sx, sy, sz), origin, cell_size = normalize_metadata(metadata)
    occ = np.zeros((sx, sy, sz), dtype=bool)

    try:
        points = np.asarray(solid_list, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3:
            return None

        rel = (points - origin.reshape(1, 3)) / cell_size
        idx = np.floor(rel).astype(np.int64)
        valid = (
            (idx[:, 0] >= 0) & (idx[:, 0] < sx)
            & (idx[:, 1] >= 0) & (idx[:, 1] < sy)
            & (idx[:, 2] >= 0) & (idx[:, 2] < sz)
        )
        idx = idx[valid]
        if idx.size:
            occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    except (TypeError, ValueError):
        return None

    return occ


def build_ore_grids(
    ore_cells: Iterable[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> Tuple[Dict[str, np.ndarray], Dict[str, List[List[float]]]]:
    """Build a separate boolean grid and label positions per ore type.

    Ore cells are intentionally not reduced to the outer shell.
    """
    (sx, sy, sz), origin, cell_size = normalize_metadata(metadata)
    grids: Dict[str, np.ndarray] = {}
    label_points: Dict[str, List[List[float]]] = {}

    for cell in ore_cells or []:
        if not isinstance(cell, dict):
            continue

        position = ore_position(cell)
        if not position:
            continue

        name = ore_name(cell)
        rel = (np.array(position, dtype=float) - origin) / cell_size
        ix, iy, iz = np.floor(rel).astype(np.int64)
        if 0 <= ix < sx and 0 <= iy < sy and 0 <= iz < sz:
            grids.setdefault(name, np.zeros((sx, sy, sz), dtype=bool))[ix, iy, iz] = True
            label_points.setdefault(name, []).append(position)

    return grids, label_points


def add_occ_mesh(
    plotter: pv.Plotter,
    occ: np.ndarray,
    metadata: Dict[str, Any],
    scalar_name: str,
    label: str,
    color: Any,
    *,
    style: str = "surface",
    opacity: float = 1.0,
    show_edges: bool = False,
) -> int:
    """Add a regular voxel mesh. Used only for ores, not for solid stone."""
    if occ is None or not np.any(occ):
        return 0

    (sx, sy, sz), origin, cell_size = normalize_metadata(metadata)

    image = pv.ImageData()
    image.dimensions = np.array([sx + 1, sy + 1, sz + 1])
    image.spacing = (cell_size, cell_size, cell_size)
    image.origin = origin
    image.cell_data[scalar_name] = occ.ravel(order="F").astype(np.uint8)

    mesh = image.threshold(0.5, scalars=scalar_name)
    plotter.add_mesh(
        mesh,
        style=style,
        color=color,
        opacity=opacity,
        show_edges=show_edges,
        label=label,
    )
    return int(mesh.n_cells)


def _corner_world(
    corner: Tuple[int, int, int],
    origin: np.ndarray,
    cell_size: float,
) -> Tuple[float, float, float]:
    return (
        float(origin[0] + corner[0] * cell_size),
        float(origin[1] + corner[1] * cell_size),
        float(origin[2] + corner[2] * cell_size),
    )


def build_outer_envelope_mesh_data(
    occ: np.ndarray,
    metadata: Dict[str, Any],
) -> Tuple[np.ndarray, np.ndarray, int, int, int]:
    """Build only outer envelope faces for solid cells.

    This does not rely on 6-neighbor checks. For each occupied ray line along
    X, Y, and Z it keeps only min/max cells and emits only the corresponding
    outside-facing quad. That removes the visual mass of internal voxel cubes
    even when the radar result is sparse or truncated.

    Returns:
        points, faces, envelope_cell_count, total_cell_count, face_count
    """
    if occ is None or not np.any(occ):
        return np.empty((0, 3), dtype=float), np.empty((0,), dtype=np.int64), 0, 0, 0

    (sx, sy, sz), origin, cell_size = normalize_metadata(metadata)
    occupied = np.argwhere(occ)
    total_cells = int(occupied.shape[0])

    x = occupied[:, 0]
    y = occupied[:, 1]
    z = occupied[:, 2]

    x_min = np.full((sy, sz), sx, dtype=np.int32)
    x_max = np.full((sy, sz), -1, dtype=np.int32)
    y_min = np.full((sx, sz), sy, dtype=np.int32)
    y_max = np.full((sx, sz), -1, dtype=np.int32)
    z_min = np.full((sx, sy), sz, dtype=np.int32)
    z_max = np.full((sx, sy), -1, dtype=np.int32)

    np.minimum.at(x_min, (y, z), x)
    np.maximum.at(x_max, (y, z), x)
    np.minimum.at(y_min, (x, z), y)
    np.maximum.at(y_max, (x, z), y)
    np.minimum.at(z_min, (x, y), z)
    np.maximum.at(z_max, (x, y), z)

    points: List[Tuple[float, float, float]] = []
    point_index: Dict[Tuple[int, int, int], int] = {}
    faces: List[int] = []
    envelope_cells = set()

    def vertex_id(corner: Tuple[int, int, int]) -> int:
        idx = point_index.get(corner)
        if idx is not None:
            return idx
        idx = len(points)
        point_index[corner] = idx
        points.append(_corner_world(corner, origin, cell_size))
        return idx

    def add_face(corners: Tuple[Tuple[int, int, int], ...]) -> None:
        faces.append(4)
        for corner in corners:
            faces.append(vertex_id(corner))

    for ix, iy, iz in occupied:
        ix_i = int(ix)
        iy_i = int(iy)
        iz_i = int(iz)
        has_face = False

        if ix_i == int(x_min[iy_i, iz_i]):
            add_face((
                (ix_i, iy_i, iz_i),
                (ix_i, iy_i, iz_i + 1),
                (ix_i, iy_i + 1, iz_i + 1),
                (ix_i, iy_i + 1, iz_i),
            ))
            has_face = True

        if ix_i == int(x_max[iy_i, iz_i]):
            add_face((
                (ix_i + 1, iy_i, iz_i),
                (ix_i + 1, iy_i + 1, iz_i),
                (ix_i + 1, iy_i + 1, iz_i + 1),
                (ix_i + 1, iy_i, iz_i + 1),
            ))
            has_face = True

        if iy_i == int(y_min[ix_i, iz_i]):
            add_face((
                (ix_i, iy_i, iz_i),
                (ix_i + 1, iy_i, iz_i),
                (ix_i + 1, iy_i, iz_i + 1),
                (ix_i, iy_i, iz_i + 1),
            ))
            has_face = True

        if iy_i == int(y_max[ix_i, iz_i]):
            add_face((
                (ix_i, iy_i + 1, iz_i),
                (ix_i, iy_i + 1, iz_i + 1),
                (ix_i + 1, iy_i + 1, iz_i + 1),
                (ix_i + 1, iy_i + 1, iz_i),
            ))
            has_face = True

        if iz_i == int(z_min[ix_i, iy_i]):
            add_face((
                (ix_i, iy_i, iz_i),
                (ix_i, iy_i + 1, iz_i),
                (ix_i + 1, iy_i + 1, iz_i),
                (ix_i + 1, iy_i, iz_i),
            ))
            has_face = True

        if iz_i == int(z_max[ix_i, iy_i]):
            add_face((
                (ix_i, iy_i, iz_i + 1),
                (ix_i + 1, iy_i, iz_i + 1),
                (ix_i + 1, iy_i + 1, iz_i + 1),
                (ix_i, iy_i + 1, iz_i + 1),
            ))
            has_face = True

        if has_face:
            envelope_cells.add((ix_i, iy_i, iz_i))

    face_count = len(faces) // 5
    return (
        np.asarray(points, dtype=float),
        np.asarray(faces, dtype=np.int64),
        len(envelope_cells),
        total_cells,
        face_count,
    )


def add_solid_outer_envelope_mesh(
    plotter: pv.Plotter,
    occ: np.ndarray,
    metadata: Dict[str, Any],
) -> Dict[str, int]:
    """Add only external envelope wire lines for solid voxels."""
    points, faces, envelope_cells, total_cells, face_count = build_outer_envelope_mesh_data(occ, metadata)
    if total_cells <= 0 or face_count <= 0 or points.size == 0 or faces.size == 0:
        return {
            "total_cells": total_cells,
            "visible_cells": 0,
            "hidden_cells": total_cells,
            "faces": 0,
            "points": 0,
        }

    mesh = pv.PolyData(points, faces)
    plotter.add_mesh(
        mesh,
        style="wireframe",
        color="gray",
        opacity=SOLID_LINE_OPACITY,
        line_width=SOLID_LINE_WIDTH,
        label=f"Solid lines ({envelope_cells}/{total_cells})",
        lighting=False,
    )

    return {
        "total_cells": total_cells,
        "visible_cells": int(envelope_cells),
        "hidden_cells": int(total_cells - envelope_cells),
        "faces": int(face_count),
        "points": int(points.shape[0]),
    }


def print_ore_summary(
    ore_cells: List[Dict[str, Any]],
    own_position: Optional[List[float]],
) -> None:
    """Print grouped and detailed ore list."""
    if not ore_cells:
        print("\n  Ore cells: 0")
        return

    grouped: Dict[str, List[Tuple[Optional[float], Optional[List[float]], Dict[str, Any]]]] = {}
    for cell in ore_cells:
        if not isinstance(cell, dict):
            continue

        name = ore_name(cell)
        position = ore_position(cell)
        distance = point_distance(own_position, position) if own_position and position else None
        grouped.setdefault(name, []).append((distance, position, cell))

    print(f"\n  Ore cells: {sum(len(v) for v in grouped.values())}")
    print("  Ore breakdown:")
    for name, cells in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        nearest = min((d for d, _, _ in cells if d is not None), default=None)
        nearest_text = f", nearest={nearest:.1f}m" if nearest is not None else ""
        print(f"    {name}: {len(cells)} cell(s){nearest_text}")

    print("\n  Detected ores:")
    print(f"  {'#':>3}  {'Ore':<14} {'Dist':>9}  {'Content':>10}  {'World coordinates'}")
    print(f"  {'-'*3}  {'-'*14} {'-'*9}  {'-'*10}  {'-'*45}")

    rows: List[Tuple[str, Optional[float], Optional[List[float]], Dict[str, Any]]] = []
    for name, cells in grouped.items():
        for distance, position, cell in cells:
            rows.append((name, distance, position, cell))

    rows.sort(key=lambda row: (row[1] is None, row[1] if row[1] is not None else float("inf"), row[0]))
    for index, (name, distance, position, cell) in enumerate(rows, 1):
        dist_text = f"{distance:.1f}m" if distance is not None else "N/A"
        if position:
            pos_text = f"({position[0]:.1f}, {position[1]:.1f}, {position[2]:.1f})"
        else:
            pos_text = "N/A"
        print(f"  {index:3d}  {name:<14} {dist_text:>9}  {ore_content(cell):>10}  {pos_text}")


def visualize_colored_ores(
    solid: List[List[float]],
    metadata: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    own_position: Optional[List[float]],
    ore_cells: List[Dict[str, Any]],
) -> None:
    """Visualize only the solid outer edge and all ore cells."""
    plotter = pv.Plotter()

    solid_stats = {
        "total_cells": 0,
        "visible_cells": 0,
        "hidden_cells": 0,
        "faces": 0,
        "points": 0,
    }

    solid_occ = build_occ_grid(solid, metadata)
    if solid_occ is not None and np.any(solid_occ):
        solid_stats = add_solid_outer_envelope_mesh(plotter, solid_occ, metadata)
        print(
            "Solid wire envelope: "
            f"visible={solid_stats['visible_cells']}/{solid_stats['total_cells']} cells, "
            f"hidden={solid_stats['hidden_cells']}, "
            f"faces={solid_stats['faces']}, "
            f"mesh_points={solid_stats['points']}"
        )

    ore_grids, ore_label_points = build_ore_grids(ore_cells, metadata)
    total_ore_cells = 0
    label_positions: List[List[float]] = []
    label_texts: List[str] = []
    label_colors: List[Tuple[int, int, int]] = []

    for name, occ in sorted(ore_grids.items()):
        count = int(np.sum(occ))
        if count <= 0:
            continue

        total_ore_cells += count
        color = ore_color(name)
        add_occ_mesh(
            plotter,
            occ,
            metadata,
            f"ore_{name}",
            f"{name} ({count})",
            color,
            style="surface",
            opacity=0.88,
            show_edges=True,
        )

        points = ore_label_points.get(name, [])
        if points:
            centroid = np.mean(np.asarray(points, dtype=float), axis=0).tolist()
            label_positions.append(centroid)
            label_texts.append(f"{name} ({count})")
            label_colors.append(color)

    # PyVista supports one text color per add_point_labels call, so labels are grouped by ore color.
    for color in sorted(set(label_colors)):
        positions = [p for p, c in zip(label_positions, label_colors) if c == color]
        texts = [t for t, c in zip(label_texts, label_colors) if c == color]
        if positions:
            plotter.add_point_labels(
                np.asarray(positions, dtype=float),
                texts,
                point_size=0,
                font_size=12,
                text_color=color,
                shape_opacity=0.35,
                always_visible=True,
            )

    grid_points: List[List[float]] = []
    player_points: List[List[float]] = []
    player_labels: List[str] = []

    for contact in contacts or []:
        if not isinstance(contact, dict):
            continue

        position = contact_position(contact)
        if not position:
            continue

        contact_type = contact.get("type")
        if contact_type == "grid":
            grid_points.append(position)
        elif contact_type == "player":
            player_points.append(position)
            label = contact_label(contact, "Player")
            if own_position:
                label = f"{label} ({point_distance(own_position, position):.0f} m)"
            player_labels.append(label)

    if grid_points:
        plotter.add_mesh(
            pv.PolyData(np.asarray(grid_points, dtype=float)),
            color="blue",
            point_size=16,
            render_points_as_spheres=True,
            label="Grids",
        )

    if player_points:
        plotter.add_mesh(
            pv.PolyData(np.asarray(player_points, dtype=float)),
            color="red",
            point_size=18,
            render_points_as_spheres=True,
            label="Players",
        )
        plotter.add_point_labels(
            np.asarray(player_points, dtype=float),
            player_labels,
            point_size=0,
            font_size=12,
            text_color="red",
            shape_opacity=0.35,
            always_visible=True,
        )

    if own_position:
        plotter.add_points(
            np.asarray([own_position], dtype=float),
            color="green",
            render_points_as_spheres=True,
            point_size=14,
            label="Own Position",
        )
        plotter.add_point_labels(
            np.asarray([own_position], dtype=float),
            ["Ship"],
            point_size=0,
            font_size=12,
            text_color="green",
            always_visible=True,
        )

    ore_summary = ", ".join(
        f"{name}({int(np.sum(occ))})"
        for name, occ in sorted(ore_grids.items())
        if np.any(occ)
    )
    hud_lines = [
        f"Script: {SCRIPT_VERSION}",
        f"Solid lines: {solid_stats['visible_cells']}/{solid_stats['total_cells']} cells",
        f"Solid hidden: {solid_stats['hidden_cells']} cells",
        f"Solid faces: {solid_stats['faces']}",
        f"Ore types: {len(ore_grids)}",
        f"Ore cells: {total_ore_cells}",
        f"Contacts: {len(contacts or [])}",
        f"Players: {len(player_points)}",
    ]
    if ore_summary:
        hud_lines.append(f"Ores: {ore_summary}")

    plotter.add_text("\n".join(hud_lines), position="upper_left", font_size=10)
    plotter.add_legend()
    plotter.show(title="Radar Voxels: Wire Lines + All Ores")


def process_and_visualize(
    solid: List[List[float]],
    metadata: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    grid,
    ore_cells: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Process scan data and visualize it. Keeps the old 4-argument call compatible."""
    global last_scan_signature

    ore_cells = ore_cells or []
    if not solid and not ore_cells:
        print("No solid or ore data to process.")
        return

    current_signature = (
        tuple(tuple(p[:3]) for p in (solid or [])[:10] if isinstance(p, (list, tuple)) and len(p) >= 3),
        len(solid or []),
        len(ore_cells),
        metadata.get("rev"),
    )
    if last_scan_signature == current_signature:
        return
    last_scan_signature = current_signature

    print(f"Processing scan: solid={len(solid or [])}, ore_cells={len(ore_cells or [])}, rev={metadata.get('rev')}")

    own_position = get_own_position(grid)
    visualize_colored_ores(solid or [], metadata, contacts or [], own_position, ore_cells or [])


def main() -> None:
    print(f"Script version: {SCRIPT_VERSION}")

    grid = prepare_grid("agent")
    # grid = prepare_grid("rover")
    # grid = prepare_grid("DroneBase")
    # grid = prepare_grid("farpost0")

    try:
        radar = grid.get_first_device(OreDetectorDevice)
        if not radar:
            print("No Ore Detector found on the grid.")
            return

        print(f"Found radar: {radar.name} (id={radar.device_id})")
        print("Cancelling any previous voxel scan...")
        cancel_seq = radar.cancel_scan()
        print(f"Cancel sent, seq={cancel_seq}")
        time.sleep(0.2)

        controller = RadarController(
            radar,
            radius=5000,
            cell_size=50.0,
            # ore_only=False,
            ore_only=True,
            # boundingBoxX=10,
            # boundingBoxY=1000,
            # boundingBoxZ=5000,
            # boundingBoxZ=30,
        )

        print("Starting voxel scan...")
        t0 = time.time()
        solid, metadata, contacts, ore_cells = controller.scan_voxels()
        elapsed = time.time() - t0

        if solid is None or metadata is None or contacts is None or ore_cells is None:
            print("Scan failed.")
            return

        own_position = get_own_position(grid)

        print(f"\n{'='*60}")
        print("  VOXEL DISTANCE MEASUREMENTS")
        print(f"{'='*60}")
        print(f"Ship position: {own_position}")
        print(f"Scan time: {elapsed:.2f}s")
        print(f"Solid voxels received: {len(solid)}")
        print(f"Grid: {metadata['size']}, cell_size={metadata['cellSize']}")
        print(f"Origin: {metadata['origin']}")

        if solid and own_position:
            voxel_info = []
            for point in solid:
                if not isinstance(point, (list, tuple)) or len(point) < 3:
                    continue
                distance = point_distance(own_position, point[:3])
                voxel_info.append({"world": (float(point[0]), float(point[1]), float(point[2])), "dist": distance})

            if voxel_info:
                voxel_info.sort(key=lambda item: item["dist"])
                print(f"\n  Distance range: {voxel_info[0]['dist']:.1f}m — {voxel_info[-1]['dist']:.1f}m")
                print(f"  Average: {sum(v['dist'] for v in voxel_info) / len(voxel_info):.1f}m")

                nearest = voxel_info[0]
                print(f"\n  → Ближайший воксель: {nearest['dist']:.1f}m")
                print(
                    "    World: "
                    f"({nearest['world'][0]:.1f}, {nearest['world'][1]:.1f}, {nearest['world'][2]:.1f})"
                )

        print_ore_summary(ore_cells, own_position)
        print(f"{'='*60}\n")

        print("Visualizing...")
        visualize_colored_ores(solid, metadata, contacts, own_position, ore_cells)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
