import numpy as np
import pyvista as pv
from typing import Any, Dict, List, Optional


def _as_point(value: Any) -> Optional[List[float]]:
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


class RadarVisualizer:
    """
    Visualizer for radar data: voxels, grids, players, and own position.
    """

    def __init__(self):
        self.plotter: Optional[pv.Plotter] = None

    def visualize(
        self,
        solid: List[List[float]],
        metadata: Dict[str, Any],
        contacts: List[Dict[str, Any]],
        own_position: Optional[List[float]] = None,
        ore_cells: Optional[List[Dict[str, Any]]] = None
    ):
        """Visualize solid voxels, contacts, own position, and ore cells."""
        if not solid:
            print("No solid data to visualize.")
            return

        print(f"Visualizing: {len(solid)} points")

        size = metadata["size"]
        cell_size = float(metadata["cellSize"])
        origin = np.array(metadata["origin"], dtype=float)
        size_x, size_y, size_z = size
        print(f"Grid size: {size_x}x{size_y}x{size_z}, cell_size: {cell_size}, origin: {origin}")

        # Build occupancy grid
        occ = np.zeros((size_x, size_y, size_z), dtype=bool)

        solid_arr: Optional[np.ndarray] = None
        try:
            arr = np.asarray(solid, dtype=np.float64)
            print(f"Array shape: {arr.shape}")
            if arr.ndim == 2 and arr.shape[1] == 3:
                solid_arr = arr
                rel = (arr - origin.reshape(1, 3)) / cell_size
                idx = np.floor(rel).astype(np.int64)
                print(f"Rel min/max: {rel.min(axis=0)}, {rel.max(axis=0)}")
                print(f"Idx min/max: {idx.min(axis=0)}, {idx.max(axis=0)}")
                valid = (
                    (idx[:, 0] >= 0) & (idx[:, 0] < size_x) &
                    (idx[:, 1] >= 0) & (idx[:, 1] < size_y) &
                    (idx[:, 2] >= 0) & (idx[:, 2] < size_z)
                )
                idx = idx[valid]
                print(f"Valid idx count: {idx.shape[0]}")
                if idx.size:
                    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
                    print(f"Occupied cells: {np.sum(occ)}")
        except Exception as e:
            print(f"Failed to rebuild occupancy: {e}")
            return

        # Visualize
        print("Creating plotter...")
        if self.plotter is None:
            self.plotter = pv.Plotter()

        self.plotter.clear()

        # Voxel grid
        print("Building voxel grid...")
        img = pv.ImageData()
        img.dimensions = np.array([size_x + 1, size_y + 1, size_z + 1])
        img.spacing = (cell_size, cell_size, cell_size)
        img.origin = origin
        img.cell_data["solid"] = occ.ravel(order="F")
        solid_grid = img.threshold(0.5, scalars="solid")
        print(f"Solid grid cells: {solid_grid.n_cells}")
        self.plotter.add_mesh(solid_grid, style="wireframe", color="gray", label="Solid Voxels")

        # Own position (green)
        own_point = _as_point(own_position)
        if own_point:
            if solid_arr is not None and len(solid_arr):
                nearest = float(np.min(np.linalg.norm(solid_arr - np.array(own_point), axis=1)))
                print(f"Own position: {own_point}, nearest solid point: {nearest:.2f} m")
            self.plotter.add_points(
                np.array([own_point]),
                color="green",
                render_points_as_spheres=True,
                point_size=10,
                label="Own Position",
            )

        # Grids (blue)
        grid_points = []
        for contact in contacts:
            if contact.get("type") == "grid":
                pos = _as_point(contact.get("position"))
                if pos:
                    grid_points.append(pos)

        print(f"Contacts: {len(contacts)}, grid_points: {len(grid_points)}")
        if grid_points:
            grid_cloud = pv.PolyData(grid_points)
            self.plotter.add_mesh(grid_cloud, color="blue", point_size=20, render_points_as_spheres=True, label="Grids")

        # Players (red)
        player_points = []
        for contact in contacts:
            if contact.get("type") == "player":
                pos = _as_point(contact.get("position"))
                if pos:
                    player_points.append(pos)

        if player_points:
            player_cloud = pv.PolyData(player_points)
            self.plotter.add_mesh(player_cloud, color="red", point_size=10, label="Players")

        # Ore cells (green voxels)
        if ore_cells:
            ore_occ = np.zeros((size_x, size_y, size_z), dtype=bool)
            for ore in ore_cells:
                pos = _as_point(ore.get("position"))
                if pos:
                    rel = (np.array(pos, dtype=float) - origin) / cell_size
                    idx = np.floor(rel).astype(np.int64)
                    if (0 <= idx[0] < size_x) and (0 <= idx[1] < size_y) and (0 <= idx[2] < size_z):
                        ore_occ[idx[0], idx[1], idx[2]] = True

            if np.any(ore_occ):
                ore_img = pv.ImageData()
                ore_img.dimensions = np.array([size_x + 1, size_y + 1, size_z + 1])
                ore_img.spacing = (cell_size, cell_size, cell_size)
                ore_img.origin = origin
                ore_img.cell_data["ore"] = ore_occ.ravel(order="F")
                ore_grid = ore_img.threshold(0.5, scalars="ore")
                print(f"Ore grid cells: {ore_grid.n_cells}")
                self.plotter.add_mesh(ore_grid, style="surface", color="green", opacity=0.85, label="Ores")

        self.plotter.add_text(f"Radar Data (points={len(solid)})", position="upper_left")
        if own_point:
            self.plotter.add_text(f"Grid Position: {own_point}", position="upper_right")
        self.plotter.show(title="Radar Visualization")

    def close(self):
        """Close the plotter."""
        if self.plotter:
            self.plotter.close()
            self.plotter = None
