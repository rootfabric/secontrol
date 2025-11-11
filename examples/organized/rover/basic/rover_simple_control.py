"""Simple rover control using high-level RoverDevice.

This example demonstrates the use of RoverDevice for easy rover control.
"""

from __future__ import annotations

from secontrol.common import prepare_grid
from secontrol.devices import RoverDevice
import time


def main() -> None:
    grid = prepare_grid()

    # Create rover controller
    rover = RoverDevice(grid)

    if not rover.wheels:
        print("No wheel devices found on grid", grid.name)
        print("Make sure your rover has MotorSuspension blocks and they are connected to the grid.")
        return

    print(f"Found {len(rover.wheels)} wheel(s) on grid {grid.name}")
    for i, wheel in enumerate(rover.wheels):
        print(f"  Wheel {i+1}: {wheel.name or wheel.device_id}")

    grid.park_off()

    # Drive forward for 2 seconds
    speed = 0.1
    # print(f"\nDriving forward at speed {speed}...")
    # rover.drive_forward(speed)
    # time.sleep(1)

    # Drive with custom steering
    print("Driving with slight right turn...")
    rover.drive(speed, 0.3)
    time.sleep(0.5)

    # Stop
    print("Stopping...")
    rover.stop()

    grid.park_on()

    print("Demo completed.")


if __name__ == "__main__":
    main()
