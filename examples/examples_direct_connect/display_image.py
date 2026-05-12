"""Example displaying images on LCD panels in Space Engineers."""

from __future__ import annotations

import datetime
import time

from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, prepare_grid


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    client, grid = prepare_grid()

    # Find display devices
    displays = grid.find_devices_by_type(DisplayDevice)
    if not displays:
        displays = grid.find_devices_by_type("display")  # Try alias

    print(f"Found {len(displays)} display device(s):")

    # Predefined Space Engineers icon IDs
    image_ids = [
        "HUDOn",  # Power on icon
        "HUDOff",  # Power off icon
        "Warning",  # Warning triangle
        "Arrow",  # Arrow icon
        "Cross",  # Cross icon
    ]

    for i, display in enumerate(displays, 1):
        print(f"  {i}. {display.name} (ID: {display.device_id})")
        # Set mode to image
        display.set_mode("image")
        # Set images
        display.set_images(image_ids[:3])  # Use first 3 images


if __name__ == "__main__":
    main()
