"""
Fly grid "Skynet Base 1" to the nearest asteroid.

Uses the ore detector radar to discover asteroids, picks the closest one,
and flies there via fly_to_point().
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.navigation_tools import fly_to_point


GRID_NAME = "skynet-baza1"
SEARCH_RADIUS = 50_000.0
RESULT_LIMIT = 320
INCLUDE_PLANETS = False
TIMEOUT_SECONDS = 15.0
FLIGHT_SPEED_FAR = 30.0
FLIGHT_SPEED_NEAR = 5.0
ARRIVAL_DISTANCE = 50.0
MAX_FLIGHT_TIME = 600.0


def request_asteroids(
    radar: OreDetectorDevice,
    *,
    radius: float = SEARCH_RADIUS,
    limit: int = RESULT_LIMIT,
    include_planets: bool = INCLUDE_PLANETS,
    timeout: float = TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command({
        "cmd": "asteroids",
        "targetId": int(radar.device_id),
        "state": {
            "radius": float(radius),
            "limit": int(limit),
            "includePlanets": bool(include_planets),
        },
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        asteroid_index = telemetry.get("asteroidIndex")
        if not isinstance(asteroid_index, dict):
            continue
        revision = asteroid_index.get("revision")
        if asteroid_index.get("ready") and revision != previous_revision:
            return asteroid_index
    return None


def find_nearest_asteroid(asteroid_index: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = asteroid_index.get("items", [])
    if not items:
        return None
    asteroids = [i for i in items if i.get("kind") == "asteroid"]
    if not asteroids:
        asteroids = items
    return min(asteroids, key=lambda i: i.get("distance", float("inf")))


def main() -> None:
    grid = prepare_grid(GRID_NAME)
    try:
        radar = grid.get_first_device(OreDetectorDevice)
        print(f"Radar: {radar.name} (id={radar.device_id})")

        print(f"Scanning for asteroids (radius={SEARCH_RADIUS}m)...")
        asteroid_index = request_asteroids(radar, radius=SEARCH_RADIUS)
        if asteroid_index is None:
            print("Asteroid scan timed out.")
            return

        nearest = find_nearest_asteroid(asteroid_index)
        if nearest is None:
            print("No asteroids found.")
            return

        name = nearest.get("name") or "<unnamed>"
        center = nearest.get("center", [0, 0, 0])
        distance = nearest.get("distance", 0)
        surface_dist = nearest.get("surfaceDistance", 0)
        print(f"Nearest asteroid: {name}")
        print(f"  Center: {center}")
        print(f"  Distance: {distance:.0f}m")
        print(f"  Surface distance: {surface_dist:.0f}m")

        target = (float(center[0]), float(center[1]), float(center[2]))

        rc = grid.get_first_device(RemoteControlDevice)
        print(f"Remote control: {rc.name} (id={rc.device_id})")

        print("Enabling autopilot...")
        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)

        print(f"Flying to {name}...")
        final_pos = fly_to_point(
            rc,
            target,
            waypoint_name=name,
            speed_far=FLIGHT_SPEED_FAR,
            speed_near=FLIGHT_SPEED_NEAR,
            arrival_distance=ARRIVAL_DISTANCE,
            max_flight_time=MAX_FLIGHT_TIME,
        )

        if final_pos:
            dx = final_pos[0] - target[0]
            dy = final_pos[1] - target[1]
            dz = final_pos[2] - target[2]
            final_dist = (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5
            print(f"Arrived. Distance to center: {final_dist:.0f}m")
        else:
            print("Autopilot did not engage.")

        print("Stopping...")
        rc.disable()
        rc.dampeners_on()
        rc.handbrake_on()
        print("Done.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
