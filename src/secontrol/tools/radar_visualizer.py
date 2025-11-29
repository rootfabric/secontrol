import numpy as np
import pyvista as pv
from typing import Any, Dict, List, Optional


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
        own_position: Optional[List[float]] = None
    ):
        """Visualize solid voxels, contacts, and own position."""
        if not solid:
            print("No solid data to visualize.")
            return

        print(f"Visualizing: {len(solid)} points")

        size = metadata["size"]
        cell_size = float(metadata["cellSize"])
        origin = np.array(metadata["origin"], dtype=float)
        size_x, size_y, size_z = size

        # Build occupancy grid
        occ = np.zeros((size_x, size_y, size_z), dtype=bool)

        try:
            arr = np.asarray(solid, dtype=np.float64)
            if arr.ndim == 2 and arr.shape[1] == 3:
                rel = (arr - origin.reshape(1, 3)) / cell_size - 0.5
                idx = np.rint(rel).astype(np.int64)
                valid = (
                    (idx[:, 0] >= 0) & (idx[:, 0] < size_x) &
                    (idx[:, 1] >= 0) & (idx[:, 1] < size_y) &
                    (idx[:, 2] >= 0) & (idx[:, 2] < size_z)
                )
                idx = idx[valid]
                if idx.size:
                    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
        except Exception as e:
            print(f"Failed to rebuild occupancy: {e}")
            return

        # Visualize
        if self.plotter is None:
            self.plotter = pv.Plotter()

        self.plotter.clear()

        # Voxel grid
        img = pv.ImageData()
        img.dimensions = np.array([size_x + 1, size_y + 1, size_z + 1])
        img.spacing = (cell_size, cell_size, cell_size)
        img.origin = origin
        img.cell_data["solid"] = occ.ravel(order="F")
        solid_grid = img.threshold(0.5, scalars="solid")
        self.plotter.add_mesh(solid_grid, style="wireframe", color="gray", label="Solid Voxels")

        # Own position (green)
        if own_position:
            self.plotter.add_points(
                np.array([own_position]),
                color="green",
                render_points_as_spheres=True,
                point_size=10,
                label="Own Position",
            )

        # Grids (blue)
        grid_points = []
        for contact in contacts:
            if contact.get("type") == "grid":
                pos = contact.get("position")
                if pos:
                    grid_points.append(pos)

        if grid_points:
            grid_cloud = pv.PolyData(grid_points)
            self.plotter.add_mesh(grid_cloud, color="blue", point_size=10, label="Grids")

        # Players (red)
        player_points = []
        for contact in contacts:
            if contact.get("type") == "player":
                pos = contact.get("position")
                if pos:
                    player_points.append(pos)

        if player_points:
            player_cloud = pv.PolyData(player_points)
            self.plotter.add_mesh(player_cloud, color="red", point_size=10, label="Players")

        self.plotter.add_text(f"Radar Data (points={len(solid)})", position="upper_left")
        self.plotter.show(title="Radar Visualization")

    def close(self):
        """Close the plotter."""
        if self.plotter:
            self.plotter.close()
            self.plotter = None
