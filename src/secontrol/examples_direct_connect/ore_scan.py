"""List all grids available for the configured Space Engineers owner id."""

from __future__ import annotations

import json

from secontrol.redis_client import RedisEventClient
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.common import resolve_owner_id, prepare_grid


def main() -> None:
    owner_id = resolve_owner_id()
    print(owner_id)

    client, grid = prepare_grid("115490481088869274")

    ore_detector = next(
        (device for device in grid.devices.values() if isinstance(device, OreDetectorDevice)),
        None,
    )
    if ore_detector is None:
        print("No ore_detector detected on the selected grid.")
        return

    print(f"Found projector {ore_detector.device_id} named {ore_detector.name!r}")
    print("Latest telemetry snapshot:")
    import time
    while 1:
        ore_detector.scan()
        # ore_detector.scan_radius()
        time.sleep(0.1)

        # Examples of actions that can be performed from Python:
        # projector.set_flags(keep_projection=True, show_only_buildable=True)
        # projector.set_offset(0, examples, -2)
        break

if __name__ == "__main__":
    main()
