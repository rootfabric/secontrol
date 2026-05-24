"""
Show aggregated ore data from SharedMapController.

Loads all saved ore deposits from the shared map (Redis/SQLite),
groups them by material, clusters spatially, and shows chunk-level
statistics.

Usage:
    python shared_map_report.py                      # all ores
    python shared_map_report.py --material Platinum   # filter by ore type
    python shared_map_report.py --grid skynet-baza0   # use grid's owner_id
    python shared_map_report.py --chunk-size 100.0    # custom chunk size
    python shared_map_report.py --storage sqlite      # use SQLite backend

Agent output format:
    Material: Platinum — 3 clusters, 41 deposits
      @ (-56810.0, 146506.1, -134196.9): 36 deposits, spread=18.3m
      @ (-56911.4, 146581.4, -134283.0): 3 deposits, spread=12.1m
      @ (-56891.4, 146673.1, -134209.7): 2 deposits, spread=1.2m
"""
import argparse
import math
import sys
from collections import Counter, defaultdict
from typing import List, Tuple

from secontrol.common import resolve_owner_id
from secontrol.controllers import SharedMapController
from secontrol.controllers.shared_map_controller import OreHit


def cluster_ores(ores: List[OreHit], cluster_radius: float = 50.0):
    """Group nearby ore deposits into spatial clusters by material."""
    by_type = defaultdict(list)
    for ore in ores:
        by_type[ore.material].append(ore.position)

    results = []
    for material, positions in sorted(by_type.items()):
        remaining = list(positions)
        while remaining:
            seed = remaining.pop(0)
            cluster_pts = [seed]
            new_remaining = []
            for pt in remaining:
                d = math.sqrt(sum((a - b) ** 2 for a, b in zip(seed, pt)))
                if d <= cluster_radius:
                    cluster_pts.append(pt)
                else:
                    new_remaining.append(pt)
            remaining = new_remaining

            cx = sum(p[0] for p in cluster_pts) / len(cluster_pts)
            cy = sum(p[1] for p in cluster_pts) / len(cluster_pts)
            cz = sum(p[2] for p in cluster_pts) / len(cluster_pts)

            mins = [min(p[i] for p in cluster_pts) for i in range(3)]
            maxs = [max(p[i] for p in cluster_pts) for i in range(3)]
            spread = math.sqrt(sum((M - m) ** 2 for m, M in zip(mins, maxs)))

            results.append({
                "material": material,
                "center": (round(cx, 1), round(cy, 1), round(cz, 1)),
                "count": len(cluster_pts),
                "spread_m": round(spread, 1),
            })

    results.sort(key=lambda c: c["count"], reverse=True)
    return results


def show_report(args):
    owner_id = args.owner_id or resolve_owner_id()
    chunk_size = args.chunk_size

    ctrl = SharedMapController(
        owner_id=owner_id,
        chunk_size=chunk_size,
        storage_backend=args.storage,
    )
    ctrl.load()

    ores = ctrl.data.ores
    material_filter = args.material.lower() if args.material else None
    if material_filter:
        ores = [o for o in ores if o.material.lower() == material_filter]

    if not ores:
        print("No ore deposits found in SharedMapController.")
        print(f"  Owner ID: {owner_id}")
        print(f"  Storage: {args.storage}")
        print(f"  Try running a radar scan first, or check the owner_id.")
        return

    # --- By material ---
    type_counts = Counter(o.material for o in ores)
    print(f"Ore deposits by type ({sum(type_counts.values())} total):")
    for ore_type, count in type_counts.most_common():
        print(f"  {ore_type}: {count}")

    # --- Clusters ---
    clusters = cluster_ores(ores, cluster_radius=args.cluster_radius)
    if material_filter:
        clusters = [c for c in clusters if c["material"].lower() == material_filter]

    print(f"\nClusters ({len(clusters)}):")
    for i, cl in enumerate(clusters):
        print(f"  {i+1}. {cl['material']} @ {cl['center']}")
        print(f"     deposits={cl['count']}, spread={cl['spread_m']}m")

    # --- Index stats ---
    idx = ctrl._load_index()
    total_storage = 0
    try:
        total_storage = ctrl.storage.get_storage_usage()
    except Exception:
        pass

    print(f"\nChunk index:")
    print(f"  voxel chunks:  {len(idx.get('voxels', []))}")
    print(f"  visited chunks: {len(idx.get('visited', []))}")
    print(f"  ore chunks:    {len(idx.get('ores', []))}")
    print(f"  chunk size:    {ctrl.chunk_size}m")
    print(f"  storage:       {_fmt_size(total_storage)}")

    # --- GPS markers for clusters ---
    print(f"\nGPS markers (copy-paste to SE):")
    for i, cl in enumerate(clusters):
        c = cl["center"]
        color = _ore_color(cl["material"])
        gps = f"GPS:{cl['material']}_{i+1}:{c[0]}:{c[1]}:{c[2]}:{color}:"
        print(f"  {gps}")


def _ore_color(material: str) -> str:
    palette = {
        "gold": "#FF8800",
        "silver": "#A0A0A0",
        "platinum": "#00FF88",
        "iron": "#FF4444",
        "nickel": "#88AA44",
        "cobalt": "#4444FF",
        "magnesium": "#FFFFFF",
        "silicon": "#888888",
        "uranium": "#44FF44",
        "ice": "#88FFFF",
    }
    return palette.get(material.lower(), "#FF8800")


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 ** 2:.1f} MB"


def main():
    parser = argparse.ArgumentParser(description="Show aggregated ore data from SharedMapController")
    parser.add_argument("--material", default=None, help="Filter by ore type (Gold, Platinum, etc.)")
    parser.add_argument("--grid", default=None, help="Grid name to derive owner_id (instead of --owner-id)")
    parser.add_argument("--owner-id", default=None, help="Owner ID (auto-resolved if not set)")
    parser.add_argument("--chunk-size", type=float, default=100.0, help="Map chunk size (default: 100)")
    parser.add_argument("--cluster-radius", type=float, default=50.0, help="Cluster merge radius in meters (default: 50)")
    parser.add_argument("--storage", default="redis", choices=["redis", "sqlite"], help="Storage backend")
    args = parser.parse_args()

    if args.grid and not args.owner_id:
        from secontrol.common import prepare_grid
        grid = prepare_grid(args.grid)
        args.owner_id = grid.owner_id

    show_report(args)


if __name__ == "__main__":
    main()
