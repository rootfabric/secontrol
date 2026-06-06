"""Set all beacons to maximum broadcast radius (20000m / 20km)."""

from __future__ import annotations

from secontrol.common import close, get_all_grids, prepare_grid, resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grids = get_all_grids()
    if not grids:
        print("No grids found.")
        return

    MAX_RADIUS = 1000000  # 20km - maximum beacon radius in Space Engineers
    total_beacons = 0
    total_set = 0

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
                current_radius = beacon.telemetry.get("radius") if beacon.telemetry else "unknown"
                print(f"  Beacon '{beacon.name}': current radius = {current_radius}")

                if current_radius == str(MAX_RADIUS):
                    print(f"    SKIP: already at maximum ({MAX_RADIUS}m)")
                    continue

                print(f"    Setting radius to {MAX_RADIUS}m...")
                sent = beacon.send_command({
                    "cmd": "radius",
                    "value": MAX_RADIUS,
                })

                if sent > 0:
                    total_set += 1
                    print(f"    OK (published to {sent} channels)")
                else:
                    print(f"    FAILED to send command")

        finally:
            close(grid)

    print(f"\n=== Summary ===")
    print(f"Grids processed: {len(grids)}")
    print(f"Total beacons: {total_beacons}")
    print(f"Radius updated: {total_set}")


if __name__ == "__main__":
    main()