"""Rename all beacons on all grids to match their grid names."""

from __future__ import annotations

import time

from secontrol.common import close, get_all_grids, prepare_grid, resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grids = get_all_grids()
    if not grids:
        print("No grids found.")
        return

    total_renamed = 0
    total_beacons = 0

    for grid_id, grid_name in grids:
        print(f"\n--- Grid: '{grid_name}' ({grid_id}) ---")

        grid = prepare_grid(grid_id)

        try:
            beacons = [d for d in grid.devices.values() if d.device_type == "beacon"]
            if not beacons:
                print("  No beacons found.")
                continue

            total_beacons += len(beacons)
            print(f"  Found {len(beacons)} beacon(s)")

            for beacon in beacons:
                old_name = beacon.name
                if old_name == grid_name:
                    print(f"  SKIP: '{old_name}' already matches grid name")
                    continue

                print(f"  Renaming '{old_name}' -> '{grid_name}'")
                sent = beacon.send_command({
                    "cmd": "set_name",
                    "name": grid_name,
                })

                if sent > 0:
                    total_renamed += 1
                    print(f"    OK (published to {sent} channels)")
                else:
                    print(f"    FAILED to send command")

        finally:
            close(grid)

    print(f"\n=== Summary ===")
    print(f"Grids processed: {len(grids)}")
    print(f"Total beacons: {total_beacons}")
    print(f"Renamed: {total_renamed}")


if __name__ == "__main__":
    main()
