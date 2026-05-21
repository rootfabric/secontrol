"""Rover drives in a circle for 60 seconds, printing telemetry.

Enables cockpit control_wheels, disables parking and brakes,
then drives with constant steering angle.
"""

from __future__ import annotations

import math
import time

from secontrol.common import prepare_grid
from secontrol.devices.wheel_device import WheelDevice

DRIVE_DURATION = 60*5  # seconds
SPEED = 0.01
STEERING = 0.9
TELEMETRY_INTERVAL = 1.0  # seconds between telemetry prints
SCAN_INTERVAL = 1.5  # seconds between radar scans


def is_left_wheel(w: WheelDevice) -> bool:
    """Left wheels have 'mirrored' in subtype."""
    extra = (w.metadata.extra if w.metadata else None) or {}
    subtype = extra.get("subtype", "")
    return "mirrored" in subtype.lower()


def rover_drive(wheels: list[WheelDevice], speed: float, steering: float) -> None:
    """Drive rover — left=+speed, right=-speed (mirrored mounting)."""
    for w in wheels:
        w.set_steering(steering)
        if is_left_wheel(w):
            w.set_propulsion(speed)
        else:
            w.set_propulsion(-speed)


def rover_stop(wheels: list[WheelDevice]) -> None:
    for w in wheels:
        w.set_propulsion(0.0)
        w.set_steering(0.0)
        w.brake_on()


def get_own_contact(detector, grid_id: int) -> dict | None:
    """Get the rover's own contact from ore detector."""
    for c in detector.contacts():
        if c.get("type") == "grid" and c.get("id") == grid_id:
            return c
    return None


def main() -> None:
    grid = prepare_grid("Respawn Rover")
    wheels = grid.find_devices_by_type("wheel")

    if not wheels:
        print("No wheels found")
        return

    left = [w for w in wheels if is_left_wheel(w)]
    right = [w for w in wheels if not is_left_wheel(w)]
    print(f"Wheels: {len(wheels)} (left={len(left)}, right={len(right)})")

    # Enable cockpit control
    cockpits = grid.find_devices_by_type("cockpit")
    if cockpits:
        cockpit = cockpits[0]
        print(f"Enabling cockpit: {cockpit.name}")
        cockpit.enable()
        cockpit.set_control_wheels(True)
        time.sleep(0.5)

    # Disable parking and wheel brakes
    grid.park_off()
    for w in wheels:
        w.enable()
        w.brake_off()
        w.set_speed_limit(15)

    # Initial scan — high contacts_hz for fast position updates
    print("Running initial radar scan...")
    detectors = grid.find_devices_by_type("ore_detector")
    detector = detectors[0] if detectors else None
    if detector:
        detector.scan(
            include_grids=True,
            include_voxels=False,
            radius=200,
            contacts_hz=10.0,
        )
        time.sleep(2)

    # Kick-start
    print("Kick-start...")
    rover_drive(wheels, 1.0, 0.0)
    time.sleep(1)

    # Circle drive
    print(f"Circle: speed={SPEED}, steering={STEERING}, duration={DRIVE_DURATION}s")
    rover_drive(wheels, SPEED, STEERING)

    grid_id = int(grid.grid_id)
    start = time.time()
    last_telemetry = 0.0
    scan_timer = 0.0

    while True:
        elapsed = time.time() - start
        if elapsed >= DRIVE_DURATION:
            break

        now = time.time()

        # Re-scan frequently for fresh contacts
        if detector and (now - scan_timer > SCAN_INTERVAL):
            detector.scan(
                include_grids=True,
                include_voxels=False,
                radius=200,
                contacts_hz=10.0,
            )
            scan_timer = now

        # Print telemetry every TELEMETRY_INTERVAL
        if now - last_telemetry >= TELEMETRY_INTERVAL:
            spd_kph = wheels[0].grid_speed_kph()
            pos_str = "?"
            heading_str = "?"

            if detector:
                contact = get_own_contact(detector, grid_id)
                if contact:
                    p = contact.get("position", [])
                    if isinstance(p, (list, tuple)) and len(p) >= 3:
                        pos_str = f"({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f})"
                    fwd = contact.get("forward", [1, 0, 0])
                    if isinstance(fwd, (list, tuple)) and len(fwd) >= 3:
                        heading_str = f"{math.degrees(math.atan2(fwd[0], fwd[2])):.0f}deg"

            print(f"  [{elapsed:5.1f}s] {spd_kph:5.1f} kph | pos={pos_str} | heading={heading_str}")
            last_telemetry = now

        time.sleep(0.1)

    rover_stop(wheels)
    print("Stopped. Done.")
    grid.close()


if __name__ == "__main__":
    main()
