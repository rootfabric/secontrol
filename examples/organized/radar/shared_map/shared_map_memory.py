"""
SharedMapController example: scan, save, and explore.

Перенос из examples/organized/radar/intermediate/shared_map_memory.py.
Исправлены API-вызовы, добавлен аргумент --grid и ore_only scan.

Usage:
    python shared_map_memory.py --grid skynet-baza0
    python shared_map_memory.py --grid skynet-baza0 --radius 80 --no-save
"""
import argparse
import sys

from dotenv import load_dotenv

from secontrol.common import close, prepare_grid
from secontrol.controllers import RadarController, SharedMapController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

load_dotenv()


def _pick_device(devices, expected_cls):
    if not devices:
        raise RuntimeError(f"No {expected_cls.__name__} found on grid")
    return devices[0]


def main():
    parser = argparse.ArgumentParser(description="SharedMap example: scan, save, and explore")
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name or ID")
    parser.add_argument("--radius", type=int, default=80, help="Scan radius (default: 80)")
    parser.add_argument("--no-save", action="store_true", help="Dry-run, don't persist")
    parser.add_argument("--storage", default="redis", choices=["redis", "sqlite"], help="Storage backend")
    parser.add_argument("--chunk-size", type=float, default=80.0, help="Chunk size (default: 80)")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)

    radar = _pick_device(grid.find_devices_by_type(OreDetectorDevice), OreDetectorDevice)
    remote = _pick_device(grid.find_devices_by_type(RemoteControlDevice), RemoteControlDevice)

    shared_map = SharedMapController(
        owner_id=grid.owner_id,
        chunk_size=args.chunk_size,
        storage_backend=args.storage,
    )
    shared_map.load()
    print(f"Shared map prefix: {shared_map.memory_prefix}")

    # Ore-only scan + ingest
    radar_ctrl = RadarController(radar, ore_only=True, radius=args.radius, cell_size=10.0)
    solid, metadata, contacts, ore_cells = shared_map.ingest_radar_scan(
        radar_ctrl, save=not args.no_save
    )
    print(f"Scan result: solid={len(solid or [])}, contacts={len(contacts or [])}, ores={len(ore_cells or [])}")

    # Save current position
    current_pos = shared_map.add_remote_position(remote)
    if current_pos:
        print(f"RC position: ({current_pos[0]:.4f}, {current_pos[1]:.4f}, {current_pos[2]:.4f})")

    # Known ores
    known = shared_map.get_known_ores()
    if known:
        print(f"\nKnown ores ({len(known)}):")
        for ore in known:
            print(f"  {ore.material} @ {ore.position} (content={ore.content})")
    else:
        print("\nNo known ores in map.")

    # Region snapshot around ship
    if current_pos:
        region = shared_map.load_region(current_pos, radius=200.0)
        print(f"\nRegion around ship (r=200m):")
        print(f"  voxels={len(region.voxels)}, visited={len(region.visited)}, ores={len(region.ores)}")

    # Index stats
    try:
        idx = shared_map.storage.load_index()
        print(f"\nIndex:")
        print(f"  voxel chunks:  {len(idx.get('voxels', []))}")
        print(f"  visited chunks: {len(idx.get('visited', []))}")
        print(f"  ore chunks:    {len(idx.get('ores', []))}")
        print(f"  chunk size:    {shared_map.chunk_size}m")
    except Exception:
        pass

    if args.no_save:
        print("\n[Dry-run] Data NOT saved.")
    else:
        print("\nData saved.")

    close(grid)


if __name__ == "__main__":
    main()
