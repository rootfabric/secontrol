"""Rename beacon to grid name - Set beacon content to match the grid's display name."""

from __future__ import annotations

import time

from secontrol.common import close, prepare_grid, resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grid = prepare_grid()

    try:
        beacons = [d for d in grid.devices.values() if d.device_type == "beacon"]
        if not beacons:
            print("No beacons found on the selected grid.")
            return

        if len(beacons) == 1:
            beacon = beacons[0]
        else:
            target_keyword = "скайнет базы1"
            beacon = None
            for b in beacons:
                if target_keyword.lower() in b.name.lower():
                    beacon = b
                    break
            if not beacon:
                print(f"Beacon with '{target_keyword}' not found. Available beacons:")
                for b in beacons:
                    print(f"  - '{b.name}'")
                return

        current_beacon_name = beacon.name
        new_content = grid.name
        print(f"Grid name: '{grid.name}'")
        print(f"Renaming beacon '{current_beacon_name}' to: '{new_content}'")

        sent = beacon.send_command({
            "cmd": "set_name",
            "name": new_content
        })

        if sent > 0:
            print(f"Successfully sent rename command (published to {sent} channels)")
        else:
            print("Failed to send rename command")
            return

        print("Waiting 2 seconds for rename to take effect...")
        time.sleep(2.0)

        print(f"Beacon name before: '{current_beacon_name}'")
        print(f"Beacon name after: '{beacon.name}'")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
