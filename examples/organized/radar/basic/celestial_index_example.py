"""
Example of requesting loaded planets and moons from an ore detector.

The dedicated plugin handles this through OreScannerDevice commands:
``planets``, ``celestial``, ``celestial_index`` or ``list_planets``. The
response is published in ore detector telemetry as the top-level
``celestialIndex`` field.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice


GRID_NAME = "skynet-agent0"  # Replace with actual grid name
RESULT_LIMIT = 128
TIMEOUT_SECONDS = 10.0


def request_celestial_index(
    radar: OreDetectorDevice,
    *,
    limit: int = RESULT_LIMIT,
    timeout: float = TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Request celestial index telemetry and wait for a fresh result."""
    telemetry = radar.telemetry or {}
    previous = telemetry.get("celestialIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    sent = radar.send_command(
        {
            "cmd": "celestial",
            "targetId": int(radar.device_id),
            "state": {
                "limit": int(limit),
            },
        }
    )
    print(f"Celestial request sent to {radar.name} (id={radar.device_id}), messages={sent}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        celestial_index = telemetry.get("celestialIndex")

        if not isinstance(celestial_index, dict):
            continue

        revision = celestial_index.get("revision")
        if celestial_index.get("ready") and revision != previous_revision:
            return celestial_index

    return None


def print_celestial_index(celestial_index: Dict[str, Any]) -> None:
    """Print a compact celestial body summary."""
    items = celestial_index.get("items", [])
    if not isinstance(items, list):
        items = []

    print(
        "Celestial index: "
        f"rev={celestial_index.get('revision')}, "
        f"count={celestial_index.get('count', len(items))}, "
        f"totalBodies={celestial_index.get('totalBodies')}, "
        f"totalVoxelMaps={celestial_index.get('totalVoxelMaps')}"
    )

    if not items:
        print("No loaded planets or moons were reported by the server.")
        return

    def fmt_meters(value: Any) -> str:
        try:
            return f"{float(value):.1f}m"
        except (TypeError, ValueError):
            return "N/A"

    for item in items:
        name = item.get("name") or item.get("storageName") or "<unnamed>"
        kind = item.get("kind", "planet")
        center = item.get("center", [])
        approx_radius = item.get("approxRadius")
        distance = item.get("distance")
        surface_distance = item.get("surfaceDistance")

        print(
            f"- {name} ({kind}): "
            f"center={center}, "
            f"radius={fmt_meters(approx_radius)}, "
            f"distance={fmt_meters(distance)}, "
            f"surface={fmt_meters(surface_distance)}"
        )


def main() -> None:
    grid = prepare_grid(GRID_NAME)

    try:
        radar = grid.get_first_device(OreDetectorDevice)
        print(f"Found radar: {radar.name} (id={radar.device_id})")

        celestial_index = request_celestial_index(radar, limit=RESULT_LIMIT)
        if celestial_index is None:
            print("Celestial request timed out or no celestialIndex telemetry was received.")
            return

        print_celestial_index(celestial_index)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
