"""
Visualize an obstacle-aware path from the current grid to the first detected player.

The example combines the voxel visualization pattern with the A* pathfinder from
`secontrol.tools.radar_navigation`. It scans voxels and ore cells, picks the first player
contact, plans a path through free cells, and shows the route together with voxels
and resources.

Usage:
    python examples/organized/radar/basic/radar_path_to_player_visualization.py
    python examples/organized/radar/basic/radar_path_to_player_visualization.py --grid skynet-baza0
    python examples/organized/radar/basic/radar_path_to_player_visualization.py --radius 1000 --cell-size 20
"""

from __future__ import annotations

import argparse
import math
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pyvista as pv

from secontrol.common import close, prepare_grid
from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.tools.navigation_tools import get_world_position
from secontrol.tools.radar_navigation import PathFinder, PassabilityProfile, RawRadarMap


DEFAULT_GRID = "skynet-baza0"
DEFAULT_RADIUS = 500.0
DEFAULT_CELL_SIZE = 20.0
DEFAULT_SHIP_RADIUS = 30.0

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
DEFAULT_ORE_COLOR = (200, 80, 200)

Point3 = Tuple[float, float, float]


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


def contact_position(contact: Dict[str, Any]) -> Optional[List[float]]:
    return as_point(contact.get("position") or contact.get("pos"))


def ore_position(cell: Dict[str, Any]) -> Optional[List[float]]:
    """Return ore cell position, accepting the common radar formats."""
    pos = as_point(cell.get("position") or cell.get("pos") or cell.get("center"))
    if pos:
        return pos

    keys = (("centerX", "centerY", "centerZ"), ("x", "y", "z"))
    for x_key, y_key, z_key in keys:
        if x_key in cell and y_key in cell and z_key in cell:
            try:
                return [float(cell[x_key]), float(cell[y_key]), float(cell[z_key])]
            except (TypeError, ValueError):
                return None
    return None


def ore_name(cell: Dict[str, Any]) -> str:
    return str(cell.get("ore") or cell.get("material") or cell.get("type") or "Unknown")


def ore_color(name: str) -> Tuple[int, int, int]:
    for key, color in ORE_COLORS.items():
        if key.lower() in name.lower():
            return color
    return DEFAULT_ORE_COLOR


def point_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def get_own_position(grid) -> Optional[List[float]]:
    """Get current grid position from cockpit or remote control telemetry."""
    for dev_type in ("cockpit", "remote_control"):
        devices = grid.find_devices_by_type(dev_type)
        if devices:
            device = devices[0]
            device.update()
            position = get_world_position(device)
            if position:
                return [float(position[0]), float(position[1]), float(position[2])]
    return None


def contact_label(contact: Dict[str, Any], fallback: str) -> str:
    for key in ("name", "displayName", "playerName", "gridName", "id", "ownerId"):
        value = contact.get(key)
        if value not in (None, ""):
            return f"{fallback}: {value}"
    return fallback


def merge_contacts(*contact_lists: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for contacts in contact_lists:
        for contact in contacts or []:
            if not isinstance(contact, dict):
                continue
            pos = contact_position(contact)
            ctype = contact.get("type", "?")
            identity = contact.get("id") or contact.get("entityId") or contact.get("ownerId")
            key = (ctype, str(identity)) if identity is not None else (ctype, tuple(round(v, 1) for v in pos or []))
            if key in seen:
                continue
            seen.add(key)
            merged.append(contact)
    return merged


def first_player(contacts: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for contact in contacts:
        if isinstance(contact, dict) and contact.get("type") == "player" and contact_position(contact):
            return contact
    return None


def build_radar_map(solid: List[List[float]], metadata: Dict[str, Any], contacts: List[Dict[str, Any]]) -> RawRadarMap:
    """Build RawRadarMap from RadarController.scan_voxels() output."""
    size = tuple(int(v) for v in metadata["size"])
    origin = np.array(metadata["origin"], dtype=np.float64)
    cell_size = float(metadata["cellSize"])
    occ = np.zeros(size, dtype=np.bool_)

    if solid:
        arr = np.asarray(solid, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[1] == 3:
            rel = (arr - origin.reshape(1, 3)) / cell_size - 0.5
            idx = np.rint(rel).astype(np.int64)
            valid = (
                (idx[:, 0] >= 0) & (idx[:, 0] < size[0])
                & (idx[:, 1] >= 0) & (idx[:, 1] < size[1])
                & (idx[:, 2] >= 0) & (idx[:, 2] < size[2])
            )
            idx = idx[valid]
            if idx.size:
                occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True

    return RawRadarMap(
        occ=occ,
        origin=origin,
        cell_size=cell_size,
        size=size,
        revision=metadata.get("rev"),
        timestamp_ms=metadata.get("tsMs"),
        contacts=tuple(contacts),
        _inflation_cache={},
    )


def plan_path(
    radar_map: RawRadarMap,
    start: Sequence[float],
    goal: Sequence[float],
    ship_radius: float,
) -> List[Point3]:
    profile = PassabilityProfile(
        robot_radius=ship_radius,
        max_slope_degrees=90.0,
        max_step_cells=5,
        allow_vertical_movement=True,
        allow_diagonal=True,
        is_ground_vehicle=False,
    )
    pathfinder = PathFinder(radar_map, profile)
    return pathfinder.find_path_world(tuple(start), tuple(goal))


def build_ore_grids(ore_cells: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, np.ndarray]:
    origin = np.array(metadata["origin"], dtype=float)
    cell_size = float(metadata["cellSize"])
    sx, sy, sz = (int(v) for v in metadata["size"])

    grids: Dict[str, np.ndarray] = {}
    for cell in ore_cells or []:
        if not isinstance(cell, dict):
            continue
        pos = ore_position(cell)
        if not pos:
            continue
        name = ore_name(cell)
        rel = (np.array(pos, dtype=float) - origin) / cell_size
        ix, iy, iz = np.floor(rel).astype(np.int64)
        if 0 <= ix < sx and 0 <= iy < sy and 0 <= iz < sz:
            grids.setdefault(name, np.zeros((sx, sy, sz), dtype=bool))[ix, iy, iz] = True
    return grids


def add_occ_mesh(
    plotter: pv.Plotter,
    occ: np.ndarray,
    metadata: Dict[str, Any],
    scalar_name: str,
    label: str,
    color: Any,
    style: str = "surface",
    opacity: float = 1.0,
) -> int:
    if not np.any(occ):
        return 0

    sx, sy, sz = occ.shape
    img = pv.ImageData()
    img.dimensions = np.array([sx + 1, sy + 1, sz + 1])
    img.spacing = (float(metadata["cellSize"]),) * 3
    img.origin = np.array(metadata["origin"], dtype=float)
    img.cell_data[scalar_name] = occ.ravel(order="F")
    mesh = img.threshold(0.5, scalars=scalar_name)
    plotter.add_mesh(mesh, style=style, color=color, opacity=opacity, label=label)
    return int(mesh.n_cells)


def visualize(
    radar_map: RawRadarMap,
    metadata: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    ore_cells: List[Dict[str, Any]],
    own_position: List[float],
    player_contact: Dict[str, Any],
    path: List[Point3],
    ship_radius: float,
) -> None:
    plotter = pv.Plotter()

    solid_cells = add_occ_mesh(
        plotter,
        radar_map.occ,
        metadata,
        "solid",
        "Solid Voxels",
        color="gray",
        style="wireframe",
        opacity=0.35,
    )

    ore_grids = build_ore_grids(ore_cells, metadata)
    total_ore_cells = 0
    for name, occ in sorted(ore_grids.items()):
        count = int(np.sum(occ))
        total_ore_cells += count
        add_occ_mesh(
            plotter,
            occ,
            metadata,
            f"ore_{name}",
            f"{name} ({count})",
            color=ore_color(name),
            style="surface",
            opacity=0.88,
        )

    player_position = contact_position(player_contact)
    player_label = contact_label(player_contact, "Player")

    plotter.add_points(
        np.array([own_position], dtype=float),
        color="green",
        render_points_as_spheres=True,
        point_size=16,
        label="Ship",
    )
    plotter.add_point_labels(
        np.array([own_position], dtype=float),
        ["Ship"],
        point_size=0,
        font_size=12,
        text_color="green",
        always_visible=True,
    )

    if player_position:
        plotter.add_points(
            np.array([player_position], dtype=float),
            color="red",
            render_points_as_spheres=True,
            point_size=18,
            label="Target Player",
        )
        plotter.add_point_labels(
            np.array([player_position], dtype=float),
            [player_label],
            point_size=0,
            font_size=12,
            text_color="red",
            always_visible=True,
        )

    grid_points = [contact_position(c) for c in contacts if isinstance(c, dict) and c.get("type") == "grid"]
    grid_points = [p for p in grid_points if p]
    if grid_points:
        plotter.add_mesh(
            pv.PolyData(np.array(grid_points, dtype=float)),
            color="blue",
            point_size=14,
            render_points_as_spheres=True,
            label="Grids",
        )

    if path:
        path_points = np.array(path, dtype=float)
        if len(path_points) >= 2:
            line = pv.lines_from_points(path_points)
            plotter.add_mesh(line.tube(radius=max(1.0, float(metadata["cellSize"]) * 0.08)), color="red", label="A* Path")
        plotter.add_points(path_points, color="yellow", render_points_as_spheres=True, point_size=9, label="Path Points")

    distance_to_player = point_distance(own_position, player_position) if player_position else 0.0
    path_distance = 0.0
    for a, b in zip(path, path[1:]):
        path_distance += point_distance(a, b)

    ore_summary = ", ".join(f"{name}:{int(np.sum(occ))}" for name, occ in sorted(ore_grids.items()) if np.any(occ))
    hud = [
        f"Ship -> first player: {distance_to_player:.0f} m",
        f"Path: {len(path)} waypoints, {path_distance:.0f} m" if path else "Path: not found",
        f"Solid voxels: {solid_cells}",
        f"Ore cells: {total_ore_cells}",
        f"Ship radius: {ship_radius:.0f} m",
    ]
    if ore_summary:
        hud.append(f"Ores: {ore_summary}")
    plotter.add_text("\n".join(hud), position="upper_left", font_size=10)
    plotter.add_legend()
    plotter.show(title="Path to Player with Voxels and Resources")


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize A* path from ship to first player")
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name or id")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS, help="Radar scan radius in meters")
    parser.add_argument("--cell-size", type=float, default=DEFAULT_CELL_SIZE, help="Voxel cell size in meters")
    parser.add_argument("--ship-radius", type=float, default=DEFAULT_SHIP_RADIUS, help="Obstacle inflation radius in meters")
    parser.add_argument("--bbox-x", type=float, default=None, help="Optional radar bounding box X")
    parser.add_argument("--bbox-y", type=float, default=None, help="Optional radar bounding box Y")
    parser.add_argument("--bbox-z", type=float, default=None, help="Optional radar bounding box Z")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    try:
        radar = grid.get_first_device(OreDetectorDevice)
        if not radar:
            print("No Ore Detector found on the grid.")
            return

        print(f"Grid: {grid.name} (id={grid.grid_id})")
        print(f"Radar: {radar.name} (id={radar.device_id})")

        own_position = get_own_position(grid)
        if not own_position:
            print("Cannot get ship position from cockpit or remote control.")
            return

        radar.cancel_scan()
        time.sleep(0.3)

        contact_controller = RadarController(radar, radius=args.radius, cell_size=args.cell_size, ore_only=False)
        print("Scanning contacts...")
        contact_scan_contacts = contact_controller.scan_contacts() or []

        player = first_player(contact_scan_contacts)
        if not player:
            print("No players found in contact scan.")
            return
        player_position = contact_position(player)
        print(f"First player: {contact_label(player, 'Player')} at {player_position}")
        print(f"Distance from ship: {point_distance(own_position, player_position):.0f} m")

        scan_kwargs: Dict[str, Any] = {}
        if args.bbox_x is not None:
            scan_kwargs["boundingBoxX"] = args.bbox_x
        if args.bbox_y is not None:
            scan_kwargs["boundingBoxY"] = args.bbox_y
        if args.bbox_z is not None:
            scan_kwargs["boundingBoxZ"] = args.bbox_z

        print("Scanning voxels and resources...")
        voxel_controller = RadarController(
            radar,
            radius=args.radius,
            cell_size=args.cell_size,
            ore_only=False,
            **scan_kwargs,
        )
        solid, metadata, voxel_contacts, voxel_ore = voxel_controller.scan_voxels()
        if solid is None or metadata is None:
            print("Voxel scan failed.")
            return

        # Keep visualization fast: skip the separate ore-only scan for now.
        # If the full voxel scan included oreCells, show them; otherwise draw only voxels/path.
        contacts = merge_contacts(contact_scan_contacts, voxel_contacts)
        ore_for_viz = voxel_ore or []

        radar_map = build_radar_map(solid or [], metadata, contacts)
        if radar_map.world_to_index(tuple(own_position)) is None:
            print("Ship position is outside the scanned voxel map. Increase --radius or bounding box.")
            return
        if radar_map.world_to_index(tuple(player_position)) is None:
            print("Player position is outside the scanned voxel map. Increase --radius or bounding box.")
            return

        print("Planning A* path...")
        path = plan_path(radar_map, own_position, player_position, args.ship_radius)
        if path:
            print(f"Path found: {len(path)} waypoints")
        else:
            print("No path found. Visualization will still show voxels, resources, ship, and player.")

        print(
            f"Visualizing: solid={len(solid or [])}, contacts={len(contacts)}, "
            f"ore_cells={len(ore_for_viz or [])}"
        )
        visualize(
            radar_map=radar_map,
            metadata=metadata,
            contacts=contacts,
            ore_cells=ore_for_viz or [],
            own_position=own_position,
            player_contact=player,
            path=path,
            ship_radius=args.ship_radius,
        )

    finally:
        close(grid)


if __name__ == "__main__":
    main()
