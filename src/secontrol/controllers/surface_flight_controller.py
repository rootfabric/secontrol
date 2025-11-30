from __future__ import annotations
import math
from typing import Tuple, List, Optional

from secontrol.common import prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController

def _get_pos(dev) -> Optional[Tuple[float, float, float]]:
    """Read world position from device telemetry."""
    tel = dev.telemetry or {}
    pos = tel.get("worldPosition") or tel.get("position")
    if not pos:
        return None
    return (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))


def _fly_to(
    remote: RemoteControlDevice,
    target: Tuple[float, float, float],
    name: str,
    speed_far: float = 10.0,
    speed_near: float = 5.0,
):
    """Send the remote control towards a GPS point with basic logging."""
    remote.update()
    current = _get_pos(remote)
    distance = None
    if current:
        dx = target[0] - current[0]
        dy = target[1] - current[1]
        dz = target[2] - current[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)

    speed = speed_far if distance is None or distance > 30.0 else speed_near
    gps = f"GPS:{name}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    print(
        f"Sending RC to {name}: target=({target[0]:.2f}, {target[1]:.2f}, {target[2]:.2f}), "
        f"distance={distance:.2f}m" if distance is not None else "distance=unknown",
    )

    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.goto(gps, speed=speed, gps_name=name, dock=False)


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

    def _sample_surface_along_path(
        self,
        start: Tuple[float, float, float],
        direction: Tuple[float, float, float],
        distance: float,
        step: float,
    ) -> Tuple[float, float]:
        """Return (max_surface_y, last_surface_y) along the path."""
        max_surface_y = None
        last_surface_y = None

        steps = max(1, int(distance / max(step, 1e-3)))
        print(f"Sampling {steps} points along path, distance={distance:.2f}, step={step:.2f}")
        for i in range(1, steps + 1):
            t = min(distance, i * step)
            sample = (
                start[0] + direction[0] * t,
                start[1] + direction[1] * t,
                start[2] + direction[2] * t,
            )

            print(f"  Sampling at ({sample[0]:.2f}, {sample[1]:.2f}, {sample[2]:.2f})")
            surface_y = self.radar_controller.get_surface_height(sample[0], sample[2])
            if surface_y is None:
                # Log reason for None
                if self.radar_controller.occupancy_grid is None or self.radar_controller.origin is None or self.radar_controller.cell_size is None or self.radar_controller.size is None:
                    print("    No occupancy grid data available")
                else:
                    idx_x = int((sample[0] - self.radar_controller.origin[0]) / self.radar_controller.cell_size)
                    idx_z = int((sample[2] - self.radar_controller.origin[2]) / self.radar_controller.cell_size)
                    in_bounds = (0 <= idx_x < self.radar_controller.size[0] and 0 <= idx_z < self.radar_controller.size[2])
                    if not in_bounds:
                        print(f"    Out of bounds: idx_x={idx_x}, idx_z={idx_z}, grid_size=({self.radar_controller.size[0]}, {self.radar_controller.size[2]})")
                    else:
                        has_solid = False
                        for y in range(self.radar_controller.size[1] - 1, -1, -1):
                            if self.radar_controller.occupancy_grid[idx_x, y, idx_z]:
                                has_solid = True
                                break
                        if not has_solid:
                            print(f"    No solid voxels in column idx_x={idx_x}, idx_z={idx_z}")
                        else:
                            print(f"    Unexpected None despite solid voxels in column")
                continue

            print(f"    Surface height: {surface_y:.2f}")
            last_surface_y = surface_y
            if max_surface_y is None or surface_y > max_surface_y:
                max_surface_y = surface_y

        return max_surface_y if max_surface_y is not None else last_surface_y, last_surface_y

    def _compute_target_over_surface(self, pos: Tuple[float, float, float], forward: Tuple[float, float, float], distance: float, altitude: float) -> Tuple[float, float, float]:
        down = self._get_down_vector()
        horiz_dir = self._project_forward_to_horizontal(forward, down)

        target_base = (
            pos[0] + horiz_dir[0] * distance,
            pos[1] + horiz_dir[1] * distance,
            pos[2] + horiz_dir[2] * distance,
        )

        # Log occupancy grid status
        if self.radar_controller.occupancy_grid is None:
            print("Occupancy grid is None, no surface data available.")
        else:
            print(f"Occupancy grid origin: {self.radar_controller.origin}, size: {self.radar_controller.size}, cell_size: {self.radar_controller.cell_size}")

        # Sample terrain along the straight forward path to avoid drifting sideways
        cell_step = self.radar_controller.cell_size or 5.0
        max_surf, last_surf = self._sample_surface_along_path(
            pos,
            horiz_dir,
            distance,
            step=max(cell_step, 5.0),
        )

        if max_surf is not None:
            surface_y = max_surf
            target_y = surface_y + altitude
            print(
                "Computed target above surface:",
                f"base={target_base}",
                f"surface_y(max)={surface_y:.2f}",
                f"target_y={target_y:.2f}",
            )
        elif last_surf is not None:
            target_y = last_surf + altitude
            print(
                "Surface sampled only near end of path, using last point:",
                f"base={target_base}",
                f"surface_y(last)={last_surf:.2f}",
                f"target_y={target_y:.2f}",
            )
        else:
            target_y = pos[1]
            print(
                "Surface not found along path, keeping current altitude:",
                f"base={target_base}",
                f"target_y={target_y:.2f}",
            )

        target_point = (
            target_base[0],
            target_y,
            target_base[2],
        )

        return target_point

    def _find_surface_point_along_gravity(
        self,
        position: Tuple[float, float, float],
        down: Tuple[float, float, float],
        max_distance: float,
        step: float,
    ) -> Optional[Tuple[float, float, float]]:
        """
        Trace along the gravity vector to find the first solid voxel point.

        Returns the center of the first solid cell encountered or ``None`` if
        nothing is found within ``max_distance``.
        """
        if (
            self.radar_controller.occupancy_grid is None
            or self.radar_controller.origin is None
            or self.radar_controller.cell_size is None
            or self.radar_controller.size is None
        ):
            print("No voxel grid to trace against.")
            return None

        origin = self.radar_controller.origin
        cell_size = self.radar_controller.cell_size
        size_x, size_y, size_z = self.radar_controller.size

        traveled = 0.0
        while traveled <= max_distance:
            sample = (
                position[0] + down[0] * traveled,
                position[1] + down[1] * traveled,
                position[2] + down[2] * traveled,
            )

            idx_x = int((sample[0] - origin[0]) / cell_size)
            idx_y = int((sample[1] - origin[1]) / cell_size)
            idx_z = int((sample[2] - origin[2]) / cell_size)

            if 0 <= idx_x < size_x and 0 <= idx_y < size_y and 0 <= idx_z < size_z:
                if self.radar_controller.occupancy_grid[idx_x, idx_y, idx_z]:
                    return (
                        origin[0] + (idx_x + 0.5) * cell_size,
                        origin[1] + (idx_y + 0.5) * cell_size,
                        origin[2] + (idx_z + 0.5) * cell_size,
                    )

            traveled += step

        return None

    def lift_drone_to_altitude(
        self,
        altitude: float,
        trace_step: Optional[float] = None,
        trace_distance: Optional[float] = None,
    ):
        """
        Move the grid to stay ``altitude`` meters above the nearest surface
        along the gravity vector.
        """
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        if self.radar_controller.occupancy_grid is None:
            print("No radar occupancy grid, performing scan...")
            self.scan_voxels()

        cell_size = self.radar_controller.cell_size or 5.0
        max_trace = trace_distance or cell_size * (self.radar_controller.size[1] if self.radar_controller.size else 50)
        step = trace_step or cell_size

        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        surface_point = self._find_surface_point_along_gravity(pos, down, max_trace, step)
        if surface_point is None:
            # Fallback to vertical lookup using x/z column
            surface_height = self.radar_controller.get_surface_height(pos[0], pos[2])
            if surface_height is not None:
                surface_point = (pos[0], surface_height, pos[2])
                print("Surface found via vertical lookup.")
            else:
                print("Surface not found; moving along up vector from current position.")
                surface_point = pos

        target_point = (
            surface_point[0] + up[0] * altitude,
            surface_point[1] + up[1] * altitude,
            surface_point[2] + up[2] * altitude,
        )

        print(
            f"Lifting to altitude: surface={surface_point}, target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
        )

        self.visited_points.append(pos)
        self.grid.create_gps_marker("LiftTarget", coordinates=target_point)
        _fly_to(self.rc, target_point, "LiftToAltitude", speed_far=10.0, speed_near=5.0)

        new_pos = _get_pos(self.rc)
        if new_pos:
            self.visited_points.append(new_pos)

    def calculate_surface_point_at_altitude(
        self,
        position: Tuple[float, float, float],
        altitude: float,
    ) -> Tuple[float, float, float]:
        """
        Calculate a point at the specified altitude above the surface for given coordinates.

        Uses gravity-based tracing to find the surface point below the given position, then adds altitude along the up vector.
        More low-level than lift_drone_to_altitude, operates on any position.
        """
        cell_size = self.radar_controller.cell_size or 5.0
        max_trace = cell_size * (self.radar_controller.size[1] if self.radar_controller.size else 50)
        step = cell_size

        down = self._get_down_vector()
        surface_point = self._find_surface_point_along_gravity(position, down, max_trace, step)
        if surface_point is not None:
            up = (-down[0], -down[1], -down[2])
            target_point = (
                surface_point[0] + up[0] * altitude,
                surface_point[1] + up[1] * altitude,
                surface_point[2] + up[2] * altitude,
            )
            print(
                f"Calculated point at altitude: position=({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f}), "
                f"surface_point=({surface_point[0]:.2f}, {surface_point[1]:.2f}, {surface_point[2]:.2f}), "
                f"altitude={altitude:.2f}, target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
            )
            return target_point
        else:
            print(f"No surface found below position ({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f}), using original position")
            return position

    def fly_forward_to_altitude(self, distance: float, altitude: float):
        """
        Fly forward from the drone's nose to a point at specified altitude above surface.

        Uses the drone's forward vector to compute a target point ahead, then calculates
        the altitude above surface at that point, and flies the grid there.
        """
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        # Get forward vector
        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        # Compute forward point
        forward_point = (
            pos[0] + forward[0] * distance,
            pos[1] + forward[1] * distance,
            pos[2] + forward[2] * distance,
        )
        print(f"Forward point: ({forward_point[0]:.2f}, {forward_point[1]:.2f}, {forward_point[2]:.2f})")

        # Calculate target at altitude above surface
        target_point = self.calculate_surface_point_at_altitude(forward_point, altitude)

        print(f"Flying to target: ({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})")

        self.grid.create_gps_marker(f"ForwardAlt{distance:.0f}m_{altitude:.0f}m", coordinates=target_point)
        _fly_to(self.rc, target_point, f"FlyForwardAlt{distance:.0f}m_{altitude:.0f}m", speed_far=10.0, speed_near=5.0)

        new_pos = _get_pos(self.rc)
        if new_pos:
            self.visited_points.append(new_pos)

        print("Flight to forward altitude complete.")

    def cruise_along_surface(self, forward_distance: float, altitude: float, altitude_tolerance: float = 1.0):
        """
        Keep the craft at the desired ``altitude`` above ground and move forward.

        The controller first corrects altitude above the current voxel surface,
        then computes a forward target following the sampled terrain profile.
        """
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        if self.radar_controller.occupancy_grid is None:
            print("No radar occupancy grid, performing scan...")
            self.scan_voxels()

        current_surface = self.radar_controller.get_surface_height(pos[0], pos[2])
        if current_surface is not None:
            current_altitude = pos[1] - current_surface
            altitude_error = current_altitude - altitude
            print(
                f"Current altitude over surface: {current_altitude:.2f}m (target {altitude:.2f}m, error {altitude_error:.2f}m)"
            )
            if abs(altitude_error) > altitude_tolerance:
                correction_target = (pos[0], current_surface + altitude, pos[2])
                print(
                    f"Altitude out of tolerance (>{altitude_tolerance}m). "
                    f"Moving to corrected height at {correction_target[1]:.2f}m."
                )
                _fly_to(
                    self.rc,
                    correction_target,
                    "AdjustAltitude",
                    speed_far=5.0,
                    speed_near=3.0,
                )
                pos = _get_pos(self.rc) or pos
        else:
            print("Surface height unavailable at current position; skipping altitude correction.")

        self.visited_points.append(pos)

        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        target_point = self._compute_target_over_surface(pos, forward, forward_distance, altitude)
        self.grid.create_gps_marker(f"CruiseTarget{forward_distance:.0f}m", coordinates=target_point)

        _fly_to(
            self.rc,
            target_point,
            f"CruiseForward{forward_distance:.0f}m",
            speed_far=10.0,
            speed_near=5.0,
        )

        new_pos = _get_pos(self.rc)
        if new_pos:
            self.visited_points.append(new_pos)

        print("Cruise complete.")

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

        # _fly_to(
        #     self.rc,
        #     target_point,
        #     f"MoveForward{distance:.0f}m",
        #     speed_far=10.0,
        #     speed_near=5.0,
        # )

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
    solid, metadata, contacts, ore_cells = controller.scan_voxels()


    controller._find_surface_point_along_gravity

    # Visualize radar data
    # from secontrol.tools.radar_visualizer import RadarVisualizer
    # visualizer = RadarVisualizer()
    # own_pos = _get_pos(controller.rc)
    # print(solid)
    # visualizer.visualize(solid, metadata, contacts, own_position=own_pos, ore_cells=ore_cells)

    controller.fly_forward_over_surface(10, 10)
    print("Visited points:", controller.get_visited_points())
