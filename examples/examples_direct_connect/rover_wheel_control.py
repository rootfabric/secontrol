"""Demonstration of controlling rover wheels for steering and propulsion.

This example shows how to control MotorSuspension devices (which are mapped to 'wheel' type)
on rovers. The wheels are automatically discovered from telemetry keys, including those
from subgrids where the physical wheels are located.
"""

from __future__ import annotations

from virtualenv.seed import wheels

from secontrol.common import prepare_grid
from secontrol.devices.wheel_device import WheelDevice
# Ensure wheel device is loaded
import secontrol.devices.wheel_device  # noqa: F401
import time


def main() -> None:
    grid = prepare_grid()


    wheels:[WheelDevice] = grid.find_devices_by_type("wheel")
    if not wheels:
        print("No wheel devices found on grid", grid.name)
        print("Make sure your rover has MotorSuspension blocks and they are connected to the grid.")
        return

    # exit(0)

    for wheel in wheels:
        wheel.normalize_propulsion_direction()

    # exit(0)

    grid.park_off()

    # for w in wheels:
    #     w.set_brake(False)
    #     w.set_propulsion_enabled(True)
    #     w.set_steering_enabled(True)   # или False для неуправляемых осей

    print(f"Found {len(wheels)} wheel(s) on grid {grid.name}")
    for i, wheel in enumerate(wheels):
        print(f"  Wheel {i+1}: {wheel.name or wheel.device_id}")

    for wheel in wheels:
        wheel.normalize_propulsion_direction()
        print(wheel.telemetry)

    # Drive forward for 3 seconds
    print("\nDriving forward...")
    for i, wheel in enumerate(wheels):
        wheel.set_steering(0)
        wheel.set_propulsion(0.2)  # Forward propulsion

    # wheels[0].set_invert_propulsion(True)
    # wheels[2].set_invert_propulsion(True)
    # wheels[3].set_invert_propulsion(True)
    # # wheels[1].set_propulsion(0.3)
            # break

        # break
    time.sleep(30)



    # Stop
    print("Stopping...")
    for wheel in wheels:
        wheel.set_propulsion(0.0)

    print("Demo completed.")

    grid.park_on()


if __name__ == "__main__":
    main()
