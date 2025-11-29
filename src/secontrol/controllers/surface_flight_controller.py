from __future__ import annotations
import math
import os
import sys
from typing import Tuple, List

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'examples'))

from secontrol.common import prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController

from examples.organized.autopilot.drone_dock_helpers import _get_pos, _fly_to


class SurfaceFlightController:
    """
    Controller for flying over planet surface using radar voxel data.
    Maintains altitude above surface and tracks visited points.
    """

    def __init__(self, grid_name: str, scan_radius = 100):
        self.grid = prepare_grid(grid_name)

        # Find devices
        radars = self.grid.find_devices_by_type(OreDetectorDevice)
        rcs = self.grid.find_devices_by_type(RemoteControlDevice)

        if not radars:
            raise RuntimeError("No OreDetector (radar) found on grid.")
        if not rcs:
            raise RuntimeError("No RemoteControl found on grid.")

        self.radar: OreDetectorDevice = radars[0]
        self.rc: RemoteControlDevice = rcs[0]

        self.radar_controller = RadarController(self.radar, radius=scan_radius)

        # Visited points
        self.visited_points: List[Tuple[float, float, float]] = []

    def scan_voxels(self):
        """Scan voxels using the radar controller."""
        return self.radar_controller.scan_voxels()

    def _get_down_vector(self) -> Tuple[float, float, float]:
        gravity_vector = self.rc.telemetry.get("gravitationalVector") if self.rc.telemetry else None
        if gravity_vector:
            g_x, g_y, g_z = gravity_vector.get("x", 0.0), gravity_vector.get("y", 0.0), gravity_vector.get("z", 0.0)
            g_len = math.sqrt(g_x ** 2 + g_y ** 2 + g_z ** 2)
            if g_len:
                return (g_x / g_len, g_y / g_len, g_z / g_len)
        return (0.0, -1.0, 0.0)

    def _project_forward_to_horizontal(self, forward: Tuple[float, float, float], down: Tuple[float, float, float]) -> Tuple[float, float, float]:
        dot_fg = forward[0] * down[0] + forward[1] * down[1] + forward[2] * down[2]
        horizontal_forward = (
            forward[0] - dot_fg * down[0],
            forward[1] - dot_fg * down[1],
            forward[2] - dot_fg * down[2],
        )

        horiz_len = math.sqrt(horizontal_forward[0] ** 2 + horizontal_forward[1] ** 2 + horizontal_forward[2] ** 2)
        if horiz_len == 0:
            print("Cannot compute horizontal forward vector, using original forward direction.")
            horiz_len = math.sqrt(forward[0] ** 2 + forward[1] ** 2 + forward[2] ** 2) or 1.0
            return (
                forward[0] / horiz_len,
                forward[1] / horiz_len,
                forward[2] / horiz_len,
            )

        return (
            horizontal_forward[0] / horiz_len,
            horizontal_forward[1] / horiz_len,
            horizontal_forward[2] / horiz_len,
        )

    def _compute_target_over_surface(self, pos: Tuple[float, float, float], forward: Tuple[float, float, float], distance: float, altitude: float) -> Tuple[float, float, float]:
        down = self._get_down_vector()
        horiz_dir = self._project_forward_to_horizontal(forward, down)

        target_base = (
            pos[0] + horiz_dir[0] * distance,
            pos[1] + horiz_dir[1] * distance,
            pos[2] + horiz_dir[2] * distance,
        )

        surface_y = self.radar_controller.get_surface_height(target_base[0], target_base[2])
        if surface_y is not None:
            target_point = (
                target_base[0],
                surface_y + altitude,
                target_base[2],
            )
            print(
                "Computed target above surface:",
                f"base={target_base}",
                f"surface_y={surface_y:.2f}",
                f"target={target_point}",
            )
        else:
            target_point = target_base
            print(f"Surface not found under base point, flying to {target_point}")

        return target_point

    def fly_forward_over_surface(self, distance: float, altitude: float):
        """Fly forward for given distance, maintaining altitude above surface."""
        print(f"Flying forward {distance}m at {altitude}m above surface.")

        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        target_point = self._compute_target_over_surface(pos, forward, distance, altitude)
        self.grid.create_gps_marker(f"Target{distance:.0f}m", coordinates=target_point)

        _fly_to(
            self.rc,
            target_point,
            f"MoveForward{distance:.0f}m",
            speed_far=10.0,
            speed_near=5.0,
        )

        pos = _get_pos(self.rc)
        if pos:
            self.visited_points.append(pos)

        print(f"Flight complete. Visited points: {len(self.visited_points)}")

    def get_visited_points(self) -> List[Tuple[float, float, float]]:
        """Get list of visited points."""
        return self.visited_points.copy()

    def return_to_start(self):
        """Return to the first visited point."""
        if len(self.visited_points) < 2:
            print("No points to return to.")
            return
        start = self.visited_points[0]
        self.fly_to_point(start[0], start[2], 10.0)  # Assume altitude 10m

    def fly_to_point(self, target_x: float, target_z: float, altitude: float):
        """Fly to specific point at altitude above surface."""
        pos = _get_pos(self.rc)
        if not pos:
            return

        self.visited_points.append(pos)

        # Adjust target_y
        surf_h = self.radar_controller.get_surface_height(target_x, target_z)
        target_y = surf_h + altitude if surf_h is not None else pos[1]

        _fly_to(
            self.rc,
            (target_x, target_y, target_z),
            f"FlyToPoint",
            speed_far=10.0,
            speed_near=5.0
        )

        pos = _get_pos(self.rc)
        if pos:
            self.visited_points.append(pos)

    def move_forward_simple(self, distance: float):
        """Move forward for given distance using ship's forward vector."""
        print(f"Moving forward {distance}m using ship's forward vector.")

        # Get current position
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        # Get forward direction
        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        # Calculate target point
        target_x = pos[0] + forward[0] * distance
        target_y = pos[1] + forward[1] * distance
        target_z = pos[2] + forward[2] * distance

        print(f"Target: ({target_x:.2f}, {target_y:.2f}, {target_z:.2f})")

        # Create GPS marker for debugging
        self.grid.create_gps_marker(f"Forward{distance:.0f}m", coordinates=(target_x, target_y, target_z))

        # Fly to target
        _fly_to(
            self.rc,
            (target_x, target_y, target_z),
            f"MoveForward{distance:.0f}m",
            speed_far=10.0,
            speed_near=5.0
        )

        # Update position
        pos = _get_pos(self.rc)
        if pos:
            self.visited_points.append(pos)

        print("Move complete.")

    def move_forward_at_altitude(self, distance: float, altitude: float):
        """Move forward horizontally and stop at a point above the surface."""
        print(f"Moving forward {distance}m at {altitude}m above surface.")

        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        forward, _, _ = self.rc.get_orientation_vectors_world()
        target_point = self._compute_target_over_surface(pos, forward, distance, altitude)

        self.grid.create_gps_marker(f"Target{distance:.0f}m", coordinates=target_point)

        _fly_to(
            self.rc,
            target_point,
            f"MoveForward{distance:.0f}m",
            speed_far=10.0,
            speed_near=5.0,
        )

        pos = _get_pos(self.rc)
        if pos:
            self.visited_points.append(pos)

        print("Move complete.")


if __name__ == "__main__":
    # Example: fly forward 50m at 10m above surface
    controller = SurfaceFlightController("taburet", scan_radius=80)  # Replace with actual grid name
    # controller.move_forward_simple(10)
    controller.scan_voxels()
    controller.fly_forward_over_surface(50, 50)
    print("Visited points:", controller.get_visited_points())
