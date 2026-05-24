"""Rename beacon example - Change the beacon content text that is visible to all players."""

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

        beacon = beacons[0]
        print(f"Found {len(beacons)} beacon(s) on grid '{grid.name}'")
        print(f"Selected beacon {beacon.device_id}: '{beacon.name}'")

        new_content = "New Beacon Content"
        print(f"Renaming beacon content to: '{new_content}'")

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

        print(f"Beacon name before: '{beacon.name}'")
        print(f"Beacon name after: '{beacon.name}'")

        if beacon.telemetry:
            print(f"Telemetry: {beacon.telemetry}")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
