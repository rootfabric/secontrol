"""Toggle the power state of the first device that supports it."""

from __future__ import annotations

import time

from secontrol.base_device import BaseDevice
from secontrol.common import close, prepare_grid, resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    client, grid = prepare_grid()

    try:
        device = next((device for device in grid.devices.values() if isinstance(device, BaseDevice)), None)
        if device is None:
            print("No devices detected on the selected grid.")
            return

        print(f"Found device {device.device_id} named {device.name!r} ({device.device_type})")
        print("Initial telemetry:", device.telemetry)
        print("Initial enabled state:", device.is_enabled())

        print("Disabling device...")
        device.set_enabled(False)
        time.sleep(1.0)
        print("Telemetry after disabling:", device.telemetry)
        print("Enabled state after disabling:", device.is_enabled())

        print("Enabling device...")
        device.set_enabled(True)
        time.sleep(1.0)
        print("Telemetry after enabling:", device.telemetry)
        print("Enabled state after enabling:", device.is_enabled())
    finally:
        close(client, grid)


if __name__ == "__main__":
    main()
