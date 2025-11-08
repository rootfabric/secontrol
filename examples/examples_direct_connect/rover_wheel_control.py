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

    # for wheel in wheels:
    #     wheel.normalize_propulsion_direction()



    grid.park_off()


    # exit()

    print(f"Found {len(wheels)} wheel(s) on grid {grid.name}")
    for i, wheel in enumerate(wheels):
        print(f"  Wheel {i+1}: {wheel.name or wheel.device_id}")

    for wheel in wheels:
        # wheel.normalize_propulsion_direction()

        print(wheel.telemetry)
    # exit()

    # Drive forward for 3 seconds

    speed = 1.5
    print("\nDriving forward...")
    for i, wheel in enumerate(wheels):
        wheel.set_steering(0)
        # wheel.set_propulsion(-0.6)  # Forward propulsion
        # wheel.set_power(100)
        # print(wheel.telemetry['invertPropulsion'])

        if 'Left' in wheel.name:
            wheel.set_propulsion(speed)  # Forward propulsion
        else:
            wheel.set_propulsion(-speed)  # Forward propulsion


    # wheels[2].set_invert_propulsion(True)
    # wheels[3].set_invert_propulsion(True)
    # # wheels[1].set_propulsion(0.3)
            # break

        # break
    time.sleep(5)



    # Stop
    print("Stopping...")
    for wheel in wheels:
        wheel.set_propulsion(0)
        wheel.set_steering(0)



    grid.park_on()

    print("Demo completed.")


if __name__ == "__main__":
    main()
