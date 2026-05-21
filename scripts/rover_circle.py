#!/usr/bin/env python3
"""Respawn Rover — езда по кругу. Left/Right определяется по subtype 'mirrored'."""

import sys, time, math
sys.path.insert(0, "/workspace/src")

from secontrol.common import close, prepare_grid
from secontrol.devices.wheel_device import WheelDevice

SPEED = 0.3
STEERING = 0.5
DURATION = 60

def is_left_wheel(w):
    """Left wheels have 'mirrored' in subtype."""
    subtype = (w.metadata.extra or {}).get("subtype", "") if w.metadata else ""
    return "mirrored" in subtype.lower()

def rover_drive(wheels, speed, steering):
    """Drive rover — left=+speed, right=-speed (mirrored mounting)."""
    for w in wheels:
        w.set_steering(steering)
        if is_left_wheel(w):
            w.set_propulsion(speed)
        else:
            w.set_propulsion(-speed)

def rover_stop(wheels):
    for w in wheels:
        w.set_propulsion(0.0)
        w.set_steering(0.0)
        w.brake_on()

grid = prepare_grid("Respawn Rover")
wheels = grid.find_devices_by_type("wheel")

left = [w for w in wheels if is_left_wheel(w)]
right = [w for w in wheels if not is_left_wheel(w)]
print(f"Колёс: {len(wheels)} (left={len(left)}, right={len(right)})")

# Disable brakes, set speed limit
for w in wheels:
    w.brake_off()
    w.set_speed_limit(15)

# Kick-start
print("Толчок...")
rover_drive(wheels, 1.0, 0.0)
time.sleep(1)

# Circle drive
print(f"Круг: speed={SPEED}, steering={STEERING}, {DURATION}s")
rover_drive(wheels, SPEED, STEERING)

# Monitor via ore detector
from secontrol.devices.ore_detector_device import OreDetectorDevice
detectors = grid.find_devices_by_type("ore_detector")
detector = detectors[0] if detectors else None

start = time.time()
while time.time() - start < DURATION:
    time.sleep(3)
    t = time.time() - start

    # Read speed from wheel telemetry
    spd_kph = wheels[0].grid_speed_kph()

    # Scan for position
    pos_str = "?"
    if detector:
        detector.scan(include_grids=True, include_voxels=False, radius=200)
        contacts = detector.contacts()
        for c in contacts:
            if c.get("type") == "grid" and c.get("id") == int(grid.grid_id):
                p = c.get("position", {})
                if isinstance(p, dict):
                    pos_str = f"({p.get('x',0):.1f}, {p.get('y',0):.1f}, {p.get('z',0):.1f})"
                elif isinstance(p, (list, tuple)) and len(p) >= 3:
                    pos_str = f"({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f})"
                break

    print(f"  t={t:4.0f}s | {spd_kph:5.1f} kph | pos={pos_str}")

# Stop
rover_stop(wheels)
print("\nОстановлен.")
close(grid)
