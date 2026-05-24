#!/usr/bin/env python3
"""
Undock and move backward without using remote-control autopilot.

This uses the grid-level `manual_thrust` command from the SE plugin. The server
selects thrusters by world thrust direction and applies override only to the
matching engines, so the ship can translate away from the connector without
turning toward a waypoint.

Usage:
  python manual_thrust_undock.py [ship_id_or_name] [distance_m] [override_pct]

Examples:
  python manual_thrust_undock.py skynet-baza0 25 20
  python manual_thrust_undock.py 104571351454649539 15 12
"""

from __future__ import annotations

import math
import os
import sys
import time

ENV_PATH = "C:/secontrol/.env"
SRC_PATH = "C:/secontrol/src"

if os.path.exists(ENV_PATH):
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from secontrol.common import prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


SHIP = sys.argv[1] if len(sys.argv) > 1 else "104571351454649539"
DISTANCE_M = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
OVERRIDE_PCT = float(sys.argv[3]) if len(sys.argv) > 3 else 18.0

PULSE_SECONDS = 0.8
MAX_SECONDS = 45.0
DOT_THRESHOLD = 0.70


def vec3(data):
    if not data:
        return None
    return (
        float(data.get("x", 0.0)),
        float(data.get("y", 0.0)),
        float(data.get("z", 0.0)),
    )


def pos(device):
    telemetry = device.telemetry or {}
    data = telemetry.get("position") or telemetry.get("pos")
    return vec3(data)


def distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def normalize(v):
    length = math.sqrt(sum(x * x for x in v))
    if length <= 1e-9:
        return (0.0, 0.0, 0.0)
    return tuple(x / length for x in v)


def as_payload(v):
    return {"x": float(v[0]), "y": float(v[1]), "z": float(v[2])}


def main() -> int:
    ship = prepare_grid(SHIP)
    time.sleep(1.0)

    connector = ship.find_devices_by_type(ConnectorDevice)[0]
    rc = ship.get_first_device(RemoteControlDevice)

    if rc:
        rc.enable()
        rc.thrusters_on()
        rc.dampeners_off()

    start_pos = pos(connector)
    if not start_pos:
        print("ERROR: connector position is unavailable")
        return 1

    orient = (connector.telemetry or {}).get("orientation") or {}
    forward = normalize(vec3(orient.get("forward")) or (0.0, 0.0, 0.0))
    if forward == (0.0, 0.0, 0.0):
        print("ERROR: connector orientation.forward is unavailable")
        return 1

    # During docking the ship connector normally points toward the target
    # connector. Moving backward means translating opposite to that forward.
    reverse = (-forward[0], -forward[1], -forward[2])

    print(f"Ship: {ship.name} ({ship.grid_id})")
    print(f"Connector: {connector.device_id}")
    print(f"Reverse direction: {reverse[0]:.3f}, {reverse[1]:.3f}, {reverse[2]:.3f}")

    print("Disconnecting connector...")
    connector.disconnect()
    time.sleep(0.8)

    elapsed = 0.0
    moved = 0.0
    try:
        while elapsed < MAX_SECONDS and moved < DISTANCE_M:
            ship.send_grid_command(
                "manual_thrust",
                payload={
                    "direction": as_payload(reverse),
                    "overridePct": OVERRIDE_PCT,
                    "threshold": DOT_THRESHOLD,
                    "enable": True,
                },
            )
            time.sleep(PULSE_SECONDS)
            elapsed += PULSE_SECONDS

            current = pos(connector)
            if current:
                moved = distance(start_pos, current)

            print(f"  t={elapsed:4.1f}s moved={moved:5.1f}m")

    finally:
        print("Clearing thrust override...")
        ship.send_grid_command("clear_thrust")
        if rc:
            rc.dampeners_on()

    print(f"DONE: moved about {moved:.1f}m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
