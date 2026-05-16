"""
Example of requesting the asteroid index from an ore detector.

The dedicated plugin handles this through OreScannerDevice commands:
``asteroids``, ``asteroid_index`` or ``list_asteroids``.  The response is
published in ore detector telemetry as the top-level ``asteroidIndex`` field.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice


GRID_NAME = "skynet-baza0"  # Replace with actual grid name
SEARCH_RADIUS = 50_000.0
RESULT_LIMIT = 320
INCLUDE_PLANETS = False
TIMEOUT_SECONDS = 10.0


def request_asteroids(
    radar: OreDetectorDevice,
    *,
    radius: float = SEARCH_RADIUS,
    limit: int = RESULT_LIMIT,
    include_planets: bool = INCLUDE_PLANETS,
    timeout: float = TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Request asteroid index telemetry and wait for a fresh result."""
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    sent = radar.send_command(
        {
            "cmd": "asteroids",
            "targetId": int(radar.device_id),
            "state": {
                "radius": float(radius),
                "limit": int(limit),
                "includePlanets": bool(include_planets),
            },
        }
    )
    print(f"Asteroid request sent to {radar.name} (id={radar.device_id}), messages={sent}")

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


def print_asteroid_index(asteroid_index: Dict[str, Any]) -> None:
    """Print a compact asteroid index summary."""
    items = asteroid_index.get("items", [])
    if not isinstance(items, list):
        items = []

    print(
        "Asteroid index: "
        f"rev={asteroid_index.get('revision')}, "
        f"radius={asteroid_index.get('radius')}m, "
        f"count={asteroid_index.get('count', len(items))}, "
        f"totalVoxelMaps={asteroid_index.get('totalVoxelMaps')}, "
        f"totalCandidates={asteroid_index.get('totalCandidates')}, "
        f"totalClusters={asteroid_index.get('totalClusters')}"
    )

    if not items:
        print("No asteroids found in the requested radius.")
        return

    def fmt_meters(value: Any) -> str:
        try:
            return f"{float(value):.1f}m"
        except (TypeError, ValueError):
            return "N/A"

    for item in items:
        name = item.get("name") or item.get("storageName") or "<unnamed>"
        kind = item.get("kind", "asteroid")
        center = item.get("center", [])
        distance = item.get("distance")
        surface_distance = item.get("surfaceDistance")
        approx_radius = item.get("approxRadius")
        voxel_map_count = item.get("voxelMapCount")

        print(
            f"- {name} ({kind}): "
            f"center={center}, "
            f"distance={fmt_meters(distance)}, "
            f"surface={fmt_meters(surface_distance)}, "
            f"approxRadius={fmt_meters(approx_radius)}, "
            f"voxelMaps={voxel_map_count}"
        )


def main() -> None:
    grid = prepare_grid(GRID_NAME)

    try:
        radar = grid.get_first_device(OreDetectorDevice)
        print(f"Found radar: {radar.name} (id={radar.device_id})")

        asteroid_index = request_asteroids(
            radar,
            radius=SEARCH_RADIUS,
            limit=RESULT_LIMIT,
            include_planets=INCLUDE_PLANETS,
        )

        if asteroid_index is None:
            print("Asteroid request timed out or no asteroidIndex telemetry was received.")
            return

        print_asteroid_index(asteroid_index)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
