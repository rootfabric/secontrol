"""Simple example to move rover forward by 10 meters using RoverDevice.

This example demonstrates how to command a rover to move forward a specific distance.
"""

from __future__ import annotations

import time
import math

from secontrol.common import prepare_grid
from secontrol.devices import RoverDevice


def main() -> None:
    grid = prepare_grid()

    # Create rover controller
    rover = RoverDevice(grid)

    if not rover.wheels:
        print("No wheel devices found on grid", grid.name)
        print("Make sure your rover has MotorSuspension blocks and they are connected to the grid.")
        return

    print(f"Found {len(rover.wheels)} wheel(s) on grid {grid.name}")

    # Perform initial scan to get position
    print("Scanning for current position...")
    rover.detector.scan(include_grids=True, include_voxels=False)
    time.sleep(2)  # Wait for telemetry update

    # Get current position and forward direction
    contacts = rover.detector.contacts()
    current_pos = None
    forward = None
    for contact in contacts:
        if contact.get("type") == "grid" and contact.get("id") == int(grid.grid_id):
            current_pos = contact.get("position")
            forward = contact.get("forward")
            break

    if not current_pos or not forward:
        print("Could not determine rover position or forward direction.")
        return

    print(f"Current position: {current_pos}")
    print(f"Forward direction: {forward}")

    # Calculate target point 10 meters ahead
    distance = 20.0
    target_point = (
        current_pos[0] + forward[0] * distance,
        current_pos[1] + forward[1] * distance,
        current_pos[2] + forward[2] * distance,
    )

    print(f"Target point: {target_point}")

    grid.park_off()
    # Move to the target point
    print("Starting move forward 10 meters...")
    rover.move_to_point(target_point, max_speed=0.1)

    print("Move completed.")


if __name__ == "__main__":
    main()
