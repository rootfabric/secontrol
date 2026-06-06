"""
Two-pass radar scan: first ore-only, then full voxels.
Shows merged result with ore deposits prioritized and colored by type.

Pass 1: ore_only=True  — finds all ore deposits across overlapping voxels
Pass 2: ore_only=False — gets full solid geometry (stone + ore)
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyvista as pv

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position


# ── Ore color map (distinct colors per ore type) ─────────────────────────
ORE_COLORS = {
    "Iron":       (180, 100, 60),
    "Nickel":     (120, 170, 80),
    "Cobalt":     (60, 140, 200),
    "Magnesium":  (220, 220, 220),
    "Silicon":    (200, 190, 140),
    "Silver":     (190, 190, 210),
    "Gold":       (255, 215, 0),
    "Platinum":   (180, 220, 240),
    "Uranium":    (80, 220, 80),
    "Uraninite":  (80, 220, 80),
    "Ice":        (140, 200, 255),
    "Stone":      (128, 128, 128),
}
DEFAULT_ORE_COLOR = (200, 80, 200)  # magenta for unknown ores

GRID_NAME = "agent2"
# GRID_NAME = "taburet3"
SCAN_RADIUS = 1000
CELL_SIZE = 10


def ore_color(name: str) -> Tuple[int, int, int]:
    """Return RGB tuple for an ore name."""
    for key, rgb in ORE_COLORS.items():
        if key.lower() in name.lower():
            return rgb
    return DEFAULT_ORE_COLOR


def contact_position(contact: Dict[str, Any]) -> Optional[List[float]]:
    """Return contact position as [x, y, z], accepting list/tuple or dict forms."""
    pos = contact.get("position")
    if isinstance(pos, dict):
        try:
            return [float(pos["x"]), float(pos["y"]), float(pos["z"])]
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(pos, (list, tuple)) and len(pos) >= 3:
        try:
            return [float(pos[0]), float(pos[1]), float(pos[2])]
        except (TypeError, ValueError):
            return None
    return None


def contact_label(contact: Dict[str, Any], prefix: str) -> str:
    """Build a compact label for a radar contact."""
    for key in ("name", "displayName", "playerName", "gridName", "id", "ownerId"):
        value = contact.get(key)
        if value not in (None, ""):
            return f"{prefix}: {value}"
    return prefix


def merge_contacts(*contact_lists: Optional[list]) -> list:
    """Merge contacts from multiple scans, deduplicating by id or rounded position."""
    merged = []
    seen = set()

    for contacts in contact_lists:
        for contact in contacts or []:
            if not isinstance(contact, dict):
                continue
            pos = contact_position(contact)
            ctype = contact.get("type", "?")
            identity = contact.get("id") or contact.get("entityId") or contact.get("ownerId")
            if identity is not None:
                key = (ctype, str(identity))
            elif pos:
                key = (ctype, tuple(round(v, 1) for v in pos))
            else:
                key = (ctype, len(merged))
            if key in seen:
                continue
            seen.add(key)
            merged.append(contact)

    return merged


def get_own_position(grid):
    """Get own world position from cockpit or remote control."""
    for dev_type in ("cockpit", "remote_control"):
        devices = grid.find_devices_by_type(dev_type)
        if devices:
            dev = devices[0]
            dev.update()
            pos = get_world_position(dev)
            if pos:
                return list(pos)
    return None


def scan_with_label(
    controller: RadarController,
    label: str,
    **overrides,
) -> Tuple[Optional[list], Optional[dict], Optional[list], Optional[list]]:
    """Run a scan and print a labeled summary."""
    print(f"\n{'='*60}")
    print(f"  SCAN: {label}")
    print(f"{'='*60}")
    solid, meta, contacts, ore_cells = controller.scan_voxels(**overrides)

    if solid is None or meta is None:
        print(f"[{label}] Scan failed or no data.")
        return None, None, None, None

    ore_count = len(ore_cells) if ore_cells else 0
    solid_count = len(solid) if solid else 0
    grid_count = sum(1 for c in contacts or [] if isinstance(c, dict) and c.get("type") == "grid")
    player_count = sum(1 for c in contacts or [] if isinstance(c, dict) and c.get("type") == "player")
    print(
        f"[{label}] solid={solid_count}, ore_cells={ore_count}, "
        f"contacts={len(contacts) if contacts else 0} (grids={grid_count}, players={player_count})"
    )

    if ore_cells:
        # Group by ore type
        ore_types: Dict[str, int] = {}
        for c in ore_cells:
            name = c.get("ore") or c.get("material") or "?"
            ore_types[name] = ore_types.get(name, 0) + 1
        print(f"[{label}] Ore breakdown:")
        for name, count in sorted(ore_types.items(), key=lambda x: -x[1]):
            print(f"    {name}: {count}")

    return solid, meta, contacts, ore_cells


def scan_contacts_with_label(controller: RadarController, label: str) -> list:
    """Run a contact-only scan and print a labeled summary."""
    print(f"\n{'='*60}")
    print(f"  SCAN: {label}")
    print(f"{'='*60}")
    contacts = controller.scan_contacts() or []
    grid_count = sum(1 for c in contacts if isinstance(c, dict) and c.get("type") == "grid")
    player_count = sum(1 for c in contacts if isinstance(c, dict) and c.get("type") == "player")
    print(f"[{label}] contacts={len(contacts)} (grids={grid_count}, players={player_count})")
    return contacts


def build_occ_grid(
    solid: list,
    metadata: dict,
) -> Optional[np.ndarray]:
    """Convert solid point list to a boolean occupancy 3D array."""
    if not solid:
        return None

    origin = np.array(metadata["origin"], dtype=float)
    cell_size = float(metadata["cellSize"])
    sx, sy, sz = metadata["size"]

    occ = np.zeros((sx, sy, sz), dtype=bool)
    try:
        arr = np.asarray(solid, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] != 3:
            return None
        rel = (arr - origin.reshape(1, 3)) / cell_size
        idx = np.floor(rel).astype(np.int64)
        valid = (
            (idx[:, 0] >= 0) & (idx[:, 0] < sx) &
            (idx[:, 1] >= 0) & (idx[:, 1] < sy) &
            (idx[:, 2] >= 0) & (idx[:, 2] < sz)
        )
        idx = idx[valid]
        if idx.size:
            occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    except Exception:
        return None
    return occ


def build_ore_grid(
    ore_cells: list,
    metadata: dict,
) -> Dict[str, np.ndarray]:
    """Build a separate boolean grid per ore type."""
    if not ore_cells:
        return {}

    origin = np.array(metadata["origin"], dtype=float)
    cell_size = float(metadata["cellSize"])
    sx, sy, sz = metadata["size"]

    grids: Dict[str, np.ndarray] = {}
    for cell in ore_cells:
        pos = cell.get("position")
        name = cell.get("ore") or cell.get("material") or "?"
        if not pos or len(pos) != 3:
            continue
        rel = (np.array(pos, dtype=float) - origin) / cell_size
        ix, iy, iz = np.floor(rel).astype(np.int64)
        if 0 <= ix < sx and 0 <= iy < sy and 0 <= iz < sz:
            if name not in grids:
                grids[name] = np.zeros((sx, sy, sz), dtype=bool)
            grids[name][ix, iy, iz] = True

    return grids


def find_connected_regions(occ: np.ndarray) -> int:
    """Count connected solid regions using 6-connectivity flood fill."""
    if occ is None or not np.any(occ):
        return 0

    sx, sy, sz = occ.shape
    visited = np.zeros_like(occ, dtype=bool)
    regions = 0

    for x in range(sx):
        for y in range(sy):
            for z in range(sz):
                if occ[x, y, z] and not visited[x, y, z]:
                    regions += 1
                    # BFS flood fill
                    stack = [(x, y, z)]
                    visited[x, y, z] = True
                    while stack:
                        cx, cy, cz = stack.pop()
                        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                            nx, ny, nz = cx+dx, cy+dy, cz+dz
                            if 0 <= nx < sx and 0 <= ny < sy and 0 <= nz < sz:
                                if occ[nx, ny, nz] and not visited[nx, ny, nz]:
                                    visited[nx, ny, nz] = True
                                    stack.append((nx, ny, nz))
    return regions


def visualize_merged(
    solid_occ: Optional[np.ndarray],
    ore_grids: Dict[str, np.ndarray],
    metadata: dict,
    contacts: list,
    own_position: Optional[list],
):
    """Visualize merged scan: solid base + ore overlays per type."""
    origin = np.array(metadata["origin"], dtype=float)
    cell_size = float(metadata["cellSize"])
    sx, sy, sz = metadata["size"]

    plotter = pv.Plotter()

    # ── Solid voxels (gray wireframe) ──
    solid_cells = 0
    if solid_occ is not None and np.any(solid_occ):
        img = pv.ImageData()
        img.dimensions = np.array([sx + 1, sy + 1, sz + 1])
        img.spacing = (cell_size, cell_size, cell_size)
        img.origin = origin
        img.cell_data["solid"] = solid_occ.ravel(order="F")
        solid_mesh = img.threshold(0.5, scalars="solid")
        solid_cells = solid_mesh.n_cells
        plotter.add_mesh(solid_mesh, style="wireframe", color="gray", opacity=0.3, label="Solid Voxels")

        # Count connected regions
        n_regions = find_connected_regions(solid_occ)
        print(f"Connected solid regions: {n_regions}")

    # ── Ore overlays (colored surfaces per type) ──
    total_ore_cells = 0
    for ore_name, ore_occ in sorted(ore_grids.items()):
        if not np.any(ore_occ):
            continue
        color = ore_color(ore_name)
        count = int(np.sum(ore_occ))
        total_ore_cells += count

        ore_img = pv.ImageData()
        ore_img.dimensions = np.array([sx + 1, sy + 1, sz + 1])
        ore_img.spacing = (cell_size, cell_size, cell_size)
        ore_img.origin = origin
        ore_img.cell_data["ore"] = ore_occ.ravel(order="F")
        ore_mesh = ore_img.threshold(0.5, scalars="ore")

        plotter.add_mesh(
            ore_mesh, style="surface",
            color=color, opacity=0.9,
            label=f"{ore_name} ({count})",
        )

    # ── Contacts ──
    grid_points = []
    player_points = []
    player_labels = []
    for c in (contacts or []):
        if not isinstance(c, dict):
            continue
        pos = contact_position(c)
        if not pos:
            continue
        if c.get("type") == "grid":
            grid_points.append(pos)
        elif c.get("type") == "player":
            player_points.append(pos)
            label = contact_label(c, "Player")
            if own_position:
                distance = float(np.linalg.norm(np.array(pos, dtype=float) - np.array(own_position, dtype=float)))
                label = f"{label} ({distance:.0f} m)"
            player_labels.append(label)

    if grid_points:
        cloud = pv.PolyData(grid_points)
        plotter.add_mesh(cloud, color="blue", point_size=20, render_points_as_spheres=True, label="Grids")

    if player_points:
        cloud = pv.PolyData(player_points)
        plotter.add_mesh(cloud, color="red", point_size=24, render_points_as_spheres=True, label="Players")
        plotter.add_point_labels(
            np.array(player_points, dtype=float),
            player_labels,
            point_size=0,
            font_size=12,
            text_color="red",
            shape_opacity=0.35,
            always_visible=True,
        )

    # ── Own position ──
    if own_position:
        plotter.add_points(
            np.array([own_position]),
            color="green", render_points_as_spheres=True,
            point_size=12, label="Own Position",
        )

    # ── HUD ──
    ore_summary = ", ".join(f"{n}({int(np.sum(o))})" for n, o in sorted(ore_grids.items()) if np.any(o))
    hud_lines = [
        f"Solid: {solid_cells} cells",
        f"Ore types: {len(ore_grids)}",
        f"Ore cells: {total_ore_cells}",
        f"Contacts: {len(contacts) if contacts else 0}",
        f"Players: {len(player_points)}",
    ]
    if ore_summary:
        hud_lines.append(f"Ores: {ore_summary}")
    plotter.add_text("\n".join(hud_lines), position="upper_left", font_size=10)

    plotter.add_legend()
    plotter.show(title="Merged Radar: Ore + Voxels")


def main() -> None:
    grid = prepare_grid(GRID_NAME)

    try:
        radar = grid.get_first_device(OreDetectorDevice)
        print(f"Radar: {radar.name} (id={radar.device_id})")

        own_position = get_own_position(grid)

        # ── PASS 1: Ore-only scan ──
        ore_controller = RadarController(radar, 
                                         radius=SCAN_RADIUS, 
                                         cell_size=CELL_SIZE,
                                         ore_only=True, 
                                         boundingBoxX=3000, 
                                         boundingBoxZ=3000, 
                                        #  boundingBoxY=2000, 
                                         )
        ore_solid, ore_meta, ore_contacts, ore_cells = scan_with_label(
            ore_controller, "ORE ONLY (ore_only=True)",
        )

        # ── PASS 2: Full voxel scan ──
        voxel_controller = RadarController(radar,
                                           radius=SCAN_RADIUS,
                                           cell_size=CELL_SIZE,
                                           ore_only=False, 
                                           boundingBoxX=3000, 
                                           boundingBoxZ=3000, 
                                        #    boundingBoxY=2000, 
                                           )
        vox_solid, vox_meta, vox_contacts, vox_ore = scan_with_label(
            voxel_controller, "FULL VOXELS (ore_only=False)",
        )

        # Contact-only scan is cheap and avoids losing players when a voxel scan
        # snapshot returns only voxel/grid data.
        contact_controller = RadarController(radar, radius=SCAN_RADIUS, cell_size=CELL_SIZE, ore_only=False)
        contact_scan_contacts = scan_contacts_with_label(contact_controller, "CONTACTS ONLY")

        # ── Merge results ──
        # Solid geometry from pass 2 (full scan)
        solid_for_viz = vox_solid if vox_solid else ore_solid
        meta_for_viz = vox_meta if vox_meta else ore_meta
        contacts_for_viz = merge_contacts(ore_contacts, vox_contacts, contact_scan_contacts)

        # Ore from pass 1 (ore-only scan has better ore data)
        ore_for_viz = ore_cells if ore_cells else (vox_ore or [])

        if not solid_for_viz or not meta_for_viz:
            print("\nNo data from either scan. Exiting.")
            return

        print(f"\n{'='*60}")
        print(f"  MERGE SUMMARY")
        print(f"{'='*60}")
        print(f"  Solid (from pass 2): {len(solid_for_viz)} points")
        print(f"  Ore cells (from pass 1): {len(ore_for_viz)}")
        print(f"  Contacts: {len(contacts_for_viz) if contacts_for_viz else 0}")
        players_for_viz = [
            c for c in contacts_for_viz or []
            if isinstance(c, dict) and c.get("type") == "player" and contact_position(c)
        ]
        if players_for_viz:
            print("  Players:")
            for player in players_for_viz:
                pos = contact_position(player)
                label = contact_label(player, "Player")
                if own_position and pos:
                    distance = float(np.linalg.norm(np.array(pos, dtype=float) - np.array(own_position, dtype=float)))
                    print(f"    {label}: pos={pos}, distance={distance:.0f} m")
                else:
                    print(f"    {label}: pos={pos}")

        # Build grids
        solid_occ = build_occ_grid(solid_for_viz, meta_for_viz)
        ore_grids = build_ore_grid(ore_for_viz, meta_for_viz)

        # Visualize
        print("\nVisualizing merged result...")
        visualize_merged(solid_occ, ore_grids, meta_for_viz, contacts_for_viz, own_position)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
