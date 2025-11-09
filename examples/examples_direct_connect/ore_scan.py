"""Subscribe to ore detector telemetry and output ore when there are updates."""

from __future__ import annotations

from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.common import resolve_owner_id, prepare_grid


def main() -> None:
    owner_id = resolve_owner_id()
    print(owner_id)

    grid = prepare_grid()

    ore_detector = next(
        (device for device in grid.devices.values() if isinstance(device, OreDetectorDevice)),
        None,
    )

    if ore_detector is None:
        print("No ore_detector detected on the selected grid.")
        return

    ore_detector.scan(include_voxels=False)
    # ore_detector.scan()

    print(ore_detector.telemetry)


if __name__ == "__main__":
    main()
