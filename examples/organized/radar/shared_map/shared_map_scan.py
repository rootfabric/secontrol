"""
Scan ores and save to SharedMapController.

Does an ore-only radar scan (radius=1000m) and immediately persists
all discovered deposits to the shared map (Redis/SQLite).
Subsequent calls to shared_map_report.py or shared_map_deposits.py
will include the new data.

Usage:
    python shared_map_scan.py --grid skynet-baza0
    python shared_map_scan.py --grid skynet-baza0 --radius 500
    python shared_map_scan.py --grid skynet-baza0 --no-save  # dry-run
"""
import argparse
import sys
import time

from secontrol.common import close, prepare_grid
from secontrol.controllers import RadarController, SharedMapController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


def main():
    parser = argparse.ArgumentParser(description="Scan ores and save to SharedMapController")
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name or ID")
    parser.add_argument("--radius", type=int, default=1000, help="Scan radius in meters (default: 1000)")
    parser.add_argument("--cell-size", type=float, default=10.0, help="Voxel cell size (default: 10)")
    parser.add_argument("--no-save", action="store_true", help="Dry-run: scan without saving to shared map")
    parser.add_argument("--chunk-size", type=float, default=100.0, help="SharedMap chunk size (default: 100)")
    parser.add_argument("--storage", default="redis", choices=["redis", "sqlite"], help="Storage backend")
    args = parser.parse_args()

    # Connect
    print(f"Connecting to grid: {args.grid}")
    grid = prepare_grid(args.grid)
    grid_id = grid.grid_id

    radars = grid.find_devices_by_type(OreDetectorDevice)
    if not radars:
        print("ERROR: No Ore Detector found on grid!")
        close(grid)
        sys.exit(1)
    radar = radars[0]

    rcs = grid.find_devices_by_type(RemoteControlDevice)
    remote = rcs[0] if rcs else None

    print(f"  Grid: {grid.name} (id={grid_id})")
    print(f"  Radar: {radar.name} (id={radar.device_id})")
    print(f"  Owner ID: {grid.owner_id}")
    if remote:
        remote.update()
        from secontrol.tools.navigation_tools import get_world_position
        pos = get_world_position(remote)
        if pos:
            print(f"  Position: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")

    # Setup shared map
    shared_map = SharedMapController(
        owner_id=grid.owner_id,
        chunk_size=args.chunk_size,
        storage_backend=args.storage,
    )
    shared_map.load()
    print(f"  Shared map prefix: {shared_map.memory_prefix}")
    print(f"  Previously known ores: {len(shared_map.get_known_ores())}")

    # Cancel any previous scan in progress
    radar.cancel_scan()
    time.sleep(0.3)

    # Scan (ore-only, wide radius)
    print(f"\nScanning ores (radius={args.radius}m, ore_only=True)...")
    radar_ctrl = RadarController(
        radar,
        ore_only=True,
        radius=args.radius,
        cell_size=args.cell_size,
        boundingBoxY=1000,
    )

    t0 = time.time()
    solid, metadata, contacts, ore_cells = shared_map.ingest_radar_scan(
        radar_ctrl, save=not args.no_save
    )
    elapsed = time.time() - t0

    # Log what the radar found
    ore_count = len(ore_cells or [])
    solid_count = len(solid or [])
    print(f"\n  Scan time: {elapsed:.1f}s")
    print(f"  Ore deposits found: {ore_count}")
    print(f"  Solid voxels: {solid_count}")

    if ore_cells:
        from collections import Counter
        types = Counter(c.get("ore") or c.get("material") or "?" for c in ore_cells)
        for ore_type, count in types.most_common():
            print(f"    {ore_type}: {count}")

    if contacts:
        print(f"  Contacts: {len(contacts)}")

    # Save position
    if remote and not args.no_save:
        pos = shared_map.add_remote_position(remote)
        if pos:
            print(f"  Position saved: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")

    # Summary
    total_ores = len(shared_map.get_known_ores())
    idx = shared_map.storage.load_index()
    print(f"\n  Total known ores in map: {total_ores}")
    print(f"  Chunks: voxels={len(idx.get('voxels',[]))}, ores={len(idx.get('ores',[]))}")

    try:
        size = shared_map.storage.get_storage_usage()
        if size < 1024:
            size_str = f"{size} B"
        elif size < 1024**2:
            size_str = f"{size/1024:.1f} KB"
        else:
            size_str = f"{size/1024**2:.1f} MB"
        print(f"  Storage: {size_str}")
    except Exception:
        pass

    if args.no_save:
        print("\n  Dry-run: data NOT saved (use without --no-save to persist)")
    else:
        print(f"\n  Data saved to {args.storage.upper()} shared map.")

    close(grid)


if __name__ == "__main__":
    main()
