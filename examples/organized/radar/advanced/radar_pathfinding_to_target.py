"""Radar-based pathfinding to target point with incremental map updates and rover control.

This example demonstrates how to use radar data from an ore detector/voxel
scanner to build an occupancy grid incrementally and find a path to a target
point using the A* algorithm from the radar_navigation module.

The map is updated incrementally as new radar packets arrive and can be
expanded to include new areas.

The rover automatically follows the calculated path using position data from
the remote control device telemetry and steering control similar to
rover_track_player.py.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple
import numpy as np

import math

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.rover_device import RoverDevice
from secontrol.tools.radar_navigation import RawRadarMap, PathFinder, PassabilityProfile


class IncrementalRadarMap:
    """A radar map that can be updated incrementally with new data."""
    
    def __init__(self, initial_cell_size: float = 2.0):
        self.cell_size = initial_cell_size
        self.occupancy_grid: Optional[np.ndarray] = None
        self.origin: Optional[np.ndarray] = None
        self.size: Optional[Tuple[int, int, int]] = None
        self.contacts = []
        self._inflation_cache = {}
        self.revision = 0
        self.timestamp_ms = 0
        
    def update_from_radar_data(self, radar_data: Dict[str, Any]):
        """Update the map with new radar data, expanding if necessary."""
        # Extract key information from the radar data
        new_origin = np.array(radar_data.get("origin", [0.0, 0.0, 0.0]), dtype=np.float64)
        new_cell_size = float(radar_data.get("cellSize", self.cell_size))
        new_size = tuple(int(v) for v in radar_data.get("size", [100, 100, 100]))  # type: ignore[index]
        
        # Update revision and timestamp
        self.revision = radar_data.get("rev", self.revision)
        self.timestamp_ms = radar_data.get("tsMs", self.timestamp_ms)
        
        # If this is the first update, initialize the grid
        if self.occupancy_grid is None:
            self.origin = new_origin
            self.size = new_size
            self.occupancy_grid = np.zeros(new_size, dtype=np.bool_)
            self.cell_size = new_cell_size
        else:
            # We need to potentially merge this new data with existing data
            # First, check if the new data overlaps with our current map
            self._merge_radar_data(radar_data, new_origin, new_size, new_cell_size)
        
        # Process solid voxels from the new data
        solid = radar_data.get("solid", [])
        if solid:
            self._add_solid_voxels(solid, new_origin, new_cell_size)
        
        # Process AABBs (Axis-Aligned Bounding Boxes) for large objects like grids
        for aabb in radar_data.get("gridsAabb", []):
            minx, miny, minz, maxx, maxy, maxz = aabb
            self._add_aabb(minx, miny, minz, maxx, maxy, maxz)
        
        # Process contacts
        for contact in radar_data.get("contacts", []):
            self.contacts.append({
                'type': str(contact.get("type", "")),
                'id': int(contact.get("id", 0)),
                'position': tuple(float(coord) for coord in contact.get("pos", [0.0, 0.0, 0.0])),
            })
    
    def _merge_radar_data(self, radar_data, new_origin, new_size, new_cell_size):
        """Merge new radar data with existing map, expanding if needed."""
        # Convert new data to our coordinate system, or expand the map if needed
        new_solid = radar_data.get("solid", [])
        
        # Calculate world bounds of new data
        new_max_x = new_origin[0] + new_size[0] * new_cell_size
        new_max_y = new_origin[1] + new_size[1] * new_cell_size
        new_max_z = new_origin[2] + new_size[2] * new_cell_size
        
        # Calculate current bounds
        current_max_x = self.origin[0] + self.size[0] * self.cell_size
        current_max_y = self.origin[1] + self.size[1] * self.cell_size
        current_max_z = self.origin[2] + self.size[2] * self.cell_size
        
        # Determine if expansion is needed
        min_x = min(self.origin[0], new_origin[0])
        min_y = min(self.origin[1], new_origin[1])
        min_z = min(self.origin[2], new_origin[2])
        max_x = max(current_max_x, new_max_x)
        max_y = max(current_max_y, new_max_y)
        max_z = max(current_max_z, new_max_z)
        
        # Calculate new size based on expanded bounds
        new_total_size = (
            int((max_x - min_x) / self.cell_size),
            int((max_y - min_y) / self.cell_size),
            int((max_z - min_z) / self.cell_size)
        )
        
        # If expansion is needed
        if (new_total_size[0] > self.size[0] or 
            new_total_size[1] > self.size[1] or 
            new_total_size[2] > self.size[2] or
            min_x < self.origin[0] or 
            min_y < self.origin[1] or 
            min_z < self.origin[2]):
            
            # Create new larger grid
            new_grid = np.zeros(new_total_size, dtype=np.bool_)
            
            # Calculate offset in grid coordinates
            offset_x = int((self.origin[0] - min_x) / self.cell_size)
            offset_y = int((self.origin[1] - min_y) / self.cell_size)
            offset_z = int((self.origin[2] - min_z) / self.cell_size)
            
            # Copy old data to the new grid at the right position
            new_grid[
                offset_x:offset_x + self.size[0],
                offset_y:offset_y + self.size[1],
                offset_z:offset_z + self.size[2]
            ] = self.occupancy_grid
            
            # Update map parameters
            self.occupancy_grid = new_grid
            self.origin = np.array([min_x, min_y, min_z])
            self.size = new_total_size
            
        # Add the new solid voxels to our expanded map
        self._add_solid_voxels(new_solid, new_origin, new_cell_size)
    
    def _add_solid_voxels(self, solid: list, origin: np.ndarray, cell_size: float):
        """Add solid voxels to the occupancy grid."""
        if not solid:
            return
            
        # Convert linear indices to 3D coordinates in the new data's coordinate system
        solid_idx = np.fromiter(solid, dtype=np.int64)
        ny, nz = self.size[1], self.size[2]
        x = solid_idx // (ny * nz)
        yz = solid_idx % (ny * nz)
        y = yz // nz
        z = yz % nz
        
        # Convert to world coordinates in the new data's system
        world_x = origin[0] + x * cell_size
        world_y = origin[1] + y * cell_size
        world_z = origin[2] + z * cell_size
        
        # Convert to grid coordinates in our map's coordinate system
        map_x = np.floor((world_x - self.origin[0]) / self.cell_size).astype(int)
        map_y = np.floor((world_y - self.origin[1]) / self.cell_size).astype(int)
        map_z = np.floor((world_z - self.origin[2]) / self.cell_size).astype(int)
        
        # Filter coordinates that are within bounds of our current map
        valid_mask = (
            (map_x >= 0) & (map_x < self.size[0]) &
            (map_y >= 0) & (map_y < self.size[1]) &
            (map_z >= 0) & (map_z < self.size[2])
        )
        
        valid_x = map_x[valid_mask]
        valid_y = map_y[valid_mask]
        valid_z = map_z[valid_mask]
        
        # Set the corresponding occupancy cells
        self.occupancy_grid[valid_x, valid_y, valid_z] = True
    
    def _add_aabb(self, minx: float, miny: float, minz: float, maxx: float, maxy: float, maxz: float):
        """Add an Axis-Aligned Bounding Box to the occupancy grid."""
        # Convert AABB bounds to grid indices
        ix0 = int((minx - self.origin[0]) / self.cell_size)
        iy0 = int((miny - self.origin[1]) / self.cell_size)
        iz0 = int((minz - self.origin[2]) / self.cell_size)
        ix1 = int((maxx - self.origin[0]) / self.cell_size)
        iy1 = int((maxy - self.origin[1]) / self.cell_size)
        iz1 = int((maxz - self.origin[2]) / self.cell_size)
        
        # Clamp to valid grid range
        ix0 = max(0, min(ix0, self.size[0] - 1))
        iy0 = max(0, min(iy0, self.size[1] - 1))
        iz0 = max(0, min(iz0, self.size[2] - 1))
        ix1 = max(0, min(ix1, self.size[0] - 1))
        iy1 = max(0, min(iy1, self.size[1] - 1))
        iz1 = max(0, min(iz1, self.size[2] - 1))
        
        if ix1 >= ix0 and iy1 >= iy0 and iz1 >= iz0:
            self.occupancy_grid[ix0:ix1+1, iy0:iy1+1, iz0:iz1+1] = True
    
    def to_raw_radar_map(self) -> RawRadarMap:
        """Convert to RawRadarMap format for use with PathFinder."""
        return RawRadarMap(
            occ=self.occupancy_grid.copy() if self.occupancy_grid is not None else np.zeros((1, 1, 1), dtype=np.bool_),
            origin=self.origin if self.origin is not None else np.array([0.0, 0.0, 0.0]),
            cell_size=self.cell_size,
            size=self.size if self.size is not None else (1, 1, 1),
            revision=self.revision,
            timestamp_ms=self.timestamp_ms,
            contacts=tuple(self.contacts),
            _inflation_cache={}
        )


def main() -> None:
    grid = prepare_grid()
    try:
        # Find ore detector device
        detectors = grid.find_devices_by_type("ore_detector")
        if not detectors:
            print("No ore detector (radar) devices found on the grid.")
            return

        # Use the first detector
        detector = detectors[0]
        print(f"Using detector: {detector.name} (ID: {detector.device_id})")

        remote_control = grid.find_devices_by_type("remote_control")[0]
        current_position = remote_control.telemetry.get('current_position')

        # Initialize rover
        rover = RoverDevice(grid)
        print(f"Found wheels: {len(rover.wheels)}")

        # Create incremental radar map
        incremental_map = IncrementalRadarMap()

        # Current pathfinder
        current_pathfinder = None
        current_path = []
        start_pos = None
        target_pos = None
        current_waypoint_index = 0

        # Rover control settings (similar to rover_track_player.py)
        MIN_DISTANCE = 5.0  # Minimum distance to waypoint
        BASE_SPEED = 0.005
        SPEED_FACTOR = 0.05
        MAX_SPEED = 0.015
        STEERING_GAIN = 2.5
        
        def on_radar_update(dev: OreDetectorDevice, telemetry: Dict[str, Any], source_event: str) -> None:
            nonlocal current_pathfinder, current_path, start_pos, target_pos

            # Extract radar data from telemetry
            radar_data = telemetry.get("radar", telemetry)

            # Check if we have any data to process
            if not radar_data:
                return

            # Update the incremental map with new data
            try:
                incremental_map.update_from_radar_data(radar_data)
                print(f"Updated incremental radar map - size: {incremental_map.size}, origin: {incremental_map.origin}, revision: {incremental_map.revision}")

                # Find grid position from contacts if not already found
                if start_pos is None:
                    grid_contact = next((c for c in incremental_map.contacts if c['type'] == 'grid' and c['id'] == int(grid.grid_id)), None)
                    if grid_contact:
                        start_pos = grid_contact['position']
                        target_pos = (start_pos[0] + 50.0, start_pos[1] + 0.0, start_pos[2] + 50.0)
                        print(f"Grid position detected: {start_pos}")
                        print(f"Target position set to: {target_pos}")
                    else:
                        print("Grid position not found in radar contacts yet, waiting for next update...")
                        return

                # Convert to RawRadarMap for pathfinding
                raw_radar_map = incremental_map.to_raw_radar_map()

                # Create pathfinder with the updated map
                profile = PassabilityProfile(
                    robot_radius=2.0,  # Robot radius in meters
                    max_slope_degrees=45.0,
                    max_step_cells=2,
                    allow_vertical_movement=True,
                    allow_diagonal=True
                )

                pathfinder = PathFinder(raw_radar_map, profile)
                current_pathfinder = pathfinder

                # Find path from grid position to target
                path = pathfinder.find_path_world(start_pos, target_pos)

                print(f"Pathfinding result: Found path with {len(path)} points")
                if path:
                    print("Path coordinates:")
                    for i, point in enumerate(path[:5]):  # Print first 5 points only
                        print(f"  {i}: ({point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f})")
                    if len(path) > 5:
                        print(f"  ... and {len(path) - 5} more points")

                    current_path = path
                else:
                    print("No path found to target. Possibly unreachable or blocked.")
                    current_path = []

            except Exception as e:
                print(f"Error processing radar data: {e}")
                import traceback
                traceback.print_exc()
        
        # Subscribe to radar updates
        detector.on("telemetry", on_radar_update)
        
        # Send initial scan command to get radar data
        print("Sending initial scan command...")
        detector.scan(
            include_players=True,
            include_grids=True,
            include_voxels=True,
            radius=100.0,  # 100m radius for good coverage
            cell_size=2.0,  # 2m resolution
            voxel_scan_hz=0.5,  # Update 0.5 times per second
            voxel_step=1,
            budget_ms_per_tick=10.0,
            fullSolidScan=True,  # Include solid voxel data
        )
        
        print("Waiting for radar data and pathfinding... Press Ctrl+C to exit")
        print("Rover will follow the calculated path automatically.")
        try:
            while True:
                time.sleep(1.0)  # Control loop at 1Hz

                # Get current rover position from remote control telemetry
                if remote_control.telemetry and 'planetPosition' in remote_control.telemetry:
                    rover_pos = tuple(remote_control.telemetry['planetPosition'])
                else:
                    continue

                # Get rover forward direction from radar contacts
                grid_contact = next((c for c in incremental_map.contacts if c['type'] == 'grid' and c['id'] == int(grid.grid_id)), None)
                if not grid_contact:
                    continue

                # For simplicity, assume forward is along the path direction
                # In a real implementation, you'd get this from the rover's orientation
                rover_forward = (1.0, 0.0, 0.0)  # Default forward direction
                print("current_path", current_path)
                if current_path and current_waypoint_index < len(current_path):
                    target_waypoint = current_path[current_waypoint_index]

                    # Calculate vector to target waypoint
                    vector_to_target = [t - r for t, r in zip(target_waypoint, rover_pos)]
                    distance = math.sqrt(sum(v**2 for v in vector_to_target))

                    if distance < MIN_DISTANCE:
                        # Reached current waypoint, move to next
                        current_waypoint_index += 1
                        if current_waypoint_index >= len(current_path):
                            print("Reached final destination!")
                            rover.stop()
                            rover.park_on()
                            break
                        else:
                            print(f"Reached waypoint {current_waypoint_index-1}, moving to next...")
                        continue

                    # Control rover movement
                    rover.park_off()

                    # Calculate speed: increases with distance
                    speed = min(MAX_SPEED, BASE_SPEED + (distance - MIN_DISTANCE) * SPEED_FACTOR)

                    # Normalize vector to target (only X and Z, ignore Y)
                    dir_to_target = [vector_to_target[0], 0, vector_to_target[2]]
                    dir_length = math.sqrt(sum(d**2 for d in dir_to_target))
                    if dir_length > 0:
                        dir_norm = [d / dir_length for d in dir_to_target]
                    else:
                        dir_norm = [1, 0, 0]  # fallback

                    # Normalize forward direction (only X and Z)
                    forward_horiz = [rover_forward[0], 0, rover_forward[2]]
                    forward_length = math.sqrt(sum(f**2 for f in forward_horiz))
                    if forward_length > 0:
                        forward_norm = [f / forward_length for f in forward_horiz]
                    else:
                        forward_norm = [1, 0, 0]  # fallback

                    # Calculate angle between forward and target direction
                    dot = sum(a*b for a,b in zip(dir_norm, forward_norm))
                    cross = dir_norm[0]*forward_norm[2] - dir_norm[2]*forward_norm[0]
                    angle = math.atan2(cross, dot)

                    # Normalize steering to -1..1
                    steering = max(-1, min(1, angle / (math.pi / 2)))
                    steering *= STEERING_GAIN
                    steering = max(-1, min(1, steering))

                    print(f"Waypoint {current_waypoint_index}: Distance {distance:.2f}, Speed {speed:.3f}, Steering {steering:.2f}")
                    rover.drive(speed, -steering)
                else:
                    # No path or finished
                    rover.stop()
                    rover.park_on()

        except KeyboardInterrupt:
            print("Stopping...")
            rover.stop()
            rover.park_on()
            
        detector.off("telemetry", on_radar_update)
        
    finally:
        close(grid)


if __name__ == "__main__":
    main()
