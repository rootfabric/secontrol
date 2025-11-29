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

    def fly_forward_over_surface(self, distance: float, altitude: float):
        """Fly forward for given distance, maintaining altitude above surface."""
        print(f"Flying forward {distance}m at {altitude}m above surface.")

        # Get current position
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        # Get forward direction
        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        remaining = distance
        segment = 10.0  # Fly in 10m segments

        while remaining > 0:
            seg = min(segment, remaining)

            # Target position
            target_x = pos[0] + forward[0] * seg
            target_z = pos[2] + forward[2] * seg

            # Adjust height to surface + altitude
            surf_h = self.radar_controller.get_surface_height(target_x, target_z)
            if surf_h is not None:
                target_y = surf_h + altitude
            else:
                target_y = pos[1]  # Keep current height

            # Debug: print target GPS
            print(f"Target GPS: GPS:Segment{seg:.0f}m:{target_x:.2f}:{target_y:.2f}:{target_z:.2f}")

            # Fly to target
            _fly_to(
                self.rc,
                (target_x, target_y, target_z),
                f"FlySegment{seg:.0f}m",
                speed_far=10.0,
                speed_near=5.0
            )

            # Update position
            pos = _get_pos(self.rc)
            if pos:
                self.visited_points.append(pos)

            remaining -= seg

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
        """Move forward for given distance, maintaining altitude above surface."""
        print(f"Moving forward {distance}m at {altitude}m above surface.")

        # Get current position
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        # Get forward direction and gravity
        forward, up, _ = self.rc.get_orientation_vectors_world()
        gravity = self.rc.telemetry.get("gravitationalVector") if self.rc.telemetry else None

        # Calculate forward_point = pos + forward * distance
        forward_point = (
            pos[0] + forward[0] * distance,
            pos[1] + forward[1] * distance,
            pos[2] + forward[2] * distance
        )

        # Find contact_point: drop down from forward_point along gravity to surface
        contact_y = self.radar_controller.get_surface_height(forward_point[0], forward_point[2])
        if contact_y is not None:
            contact_point = (forward_point[0], contact_y, forward_point[2])

            # Calculate up direction = -gravity_norm
            if gravity:
                g_x, g_y, g_z = gravity.get("x", 0), gravity.get("y", 0), gravity.get("z", 0)
                g_magnitude = math.sqrt(g_x**2 + g_y**2 + g_z**2)
                if g_magnitude > 0:
                    g_norm = (g_x / g_magnitude, g_y / g_magnitude, g_z / g_magnitude)
                    # Target point = contact_point + up * altitude = contact_point - g_norm * altitude
                    target_point = (
                        contact_point[0] - g_norm[0] * altitude,
                        contact_point[1] - g_norm[1] * altitude,
                        contact_point[2] - g_norm[2] * altitude
                    )
                else:
                    # Fallback: assume up is (0,1,0)
                    target_point = (contact_point[0], contact_point[1] + altitude, contact_point[2])
            else:
                # No gravity, assume up is (0,1,0)
                target_point = (contact_point[0], contact_point[1] + altitude, contact_point[2])

            print(f"Forward point: {forward_point}, Contact point: {contact_point}, Target point: {target_point}")
        else:
            # No surface found, fallback to forward_point
            target_point = forward_point
            print(f"No surface found at forward point, using forward point: {target_point}")

        target_x, target_y, target_z = target_point

        # Create GPS marker for debugging
        self.grid.create_gps_marker(f"Target{distance:.0f}m", coordinates=(target_x, target_y, target_z))

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


if __name__ == "__main__":
    # Example: fly forward 50m at 10m above surface
    controller = SurfaceFlightController("taburet", scan_radius=80)  # Replace with actual grid name
    # controller.move_forward_simple(10)
    controller.scan_voxels()
    controller.fly_forward_over_surface(50, 50)
    print("Visited points:", controller.get_visited_points())
