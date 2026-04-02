"""Example using the DisplayDevice class to find all displays across all player's grids and set text."""

from __future__ import annotations

import datetime
import time

from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, resolve_player_id, get_all_grids, prepare_grid




def main() -> None:

        grids = get_all_grids()
        if not grids:
            print("No grids found.")
            return

        total_displays = 0
        for grid_id, grid_name in grids:
            print(f"Processing grid: {grid_id} ({grid_name})")

            grid = prepare_grid(grid_id)

            # Find display devices
            displays = grid.find_devices_by_type(DisplayDevice)
            if not displays:
                displays = grid.find_devices_by_type("display")  # Try alias

            print(f"  Found {len(displays)} display device(s):")

            for i, display in enumerate(displays, 1):
                print(f"    {i}. {display.name} (ID: {display.device_id})")
                display.set_mode("text")
                display.set_text("Hello world!++")

            total_displays += len(displays)

        print(f"\nTotal displays found and updated: {total_displays}")





if __name__ == "__main__":
    main()
