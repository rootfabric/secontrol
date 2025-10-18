"""Basic lamp control example using :class:`LampDevice`."""

from __future__ import annotations

import time

from sepy.common import close, prepare_grid, resolve_owner_id
from sepy.devices.lamp_device import LampDevice


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    client, grid = prepare_grid()

    try:
        lamp = next((device for device in grid.devices.values() if isinstance(device, LampDevice)), None)
        if lamp is None:
            print("No lamp detected on the selected grid.")
            return

        print(f"Found lamp {lamp.device_id} named {lamp.name!r}")
        print("Initial telemetry:", lamp.telemetry)

        lamp.set_enabled(True)
        print("Lamp enabled.")

        for red, green, blue in ((1.0, 0.2, 0.2), (0.2, 1.0, 0.2), (0.2, 0.4, 1.0)):
            lamp.set_color(rgb=(red, green, blue))
            print(f"Set color to {(red, green, blue)}; telemetry color={lamp.color_rgb()}")
            time.sleep(1.0)

        lamp.set_enabled(False)
        print("Lamp disabled.")
    finally:
        close(client, grid)


if __name__ == "__main__":
    main()
