
"""Example using the DisplayDevice class with enhanced display functions."""

from __future__ import annotations

import datetime
import time

from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, prepare_grid



def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    grid = prepare_grid()


    # Find display devices
    displays = grid.find_devices_by_type(DisplayDevice)
    if not displays:
        displays = grid.find_devices_by_type("display")  # Try alias

    print(f"Found {len(displays)} display device(s):")

    for i, display in enumerate(displays, 1):
        print(f"  {i}. {display.name} (ID: {display.device_id})")
        display.set_text("Hello Mars!")





if __name__ == "__main__":
    main()
