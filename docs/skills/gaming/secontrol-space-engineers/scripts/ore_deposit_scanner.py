"""
Ore Deposit Scanner — scans ore deposits around a grid and saves coordinates.

Uses ore_only=True to avoid 256-cell truncation buffer (Stone fills it otherwise).
Clusters nearby deposits, generates GPS markers for SE copy-paste.

Usage:
    python ore_deposit_scanner.py                     # skynet-baza0, default
    python ore_deposit_scanner.py --grid DroneBase    # different grid
    python ore_deposit_scanner.py --radius 500        # smaller radius
    python ore_deposit_scanner.py --full_scan          # + full voxel geometry

Output: JSON with ore types, world coordinates, clusters, GPS markers.
Default path: /home/hermeswebui/se-data/scans/ (outside git repo)
"""

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime

# Adjust paths for your environment
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position


DATA_DIR = "/home/hermeswebui/se-data/scans"


def get_own_position(grid):
    """Get own world position from cockpit or remote control."""
    for dev_type in ["cockpit", "remote_control"]:
        devices = grid.find_devices_by_type(dev_type)
        if devices:
            devices[0].update()
            pos = get_world_position(devices[0])
            return list(pos) if pos else None
    return None


def cluster_ore_deposits(ore_cells, cluster_radius=50.0):
    """Group nearby ore deposits into clusters."""
    if not ore_cells:
        return []

    by_type = {}
    for cell in ore_cells:
        ore = cell.get("ore") or cell.get("material") or "Unknown"
        pos = cell.get("position")
        if not pos or ore in ("Stone", "", None):
            continue
        by_type.setdefault(ore, []).append(pos)

    clusters = []
    for ore_type, positions in by_type.items():
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

            clusters.append({
                "ore_type": ore_type,
                "center": [round(cx, 1), round(cy, 1), round(cz, 1)],
                "deposit_count": len(cluster_pts),
                "positions": [[round(p[0], 1), round(p[1], 1), round(p[2], 1)] for p in cluster_pts],
                "bounding_box": {"min": [round(m, 1) for m in mins], "max": [round(M, 1) for M in maxs]},
                "spread_m": round(math.sqrt(sum((M - m) ** 2 for m, M in zip(mins, maxs))), 1),
            })

    clusters.sort(key=lambda c: c["deposit_count"], reverse=True)
    return clusters


def gps_string(name, pos, color="#FF8800"):
    return f"GPS:{name}:{pos[0]}:{pos[1]}:{pos[2]}:{color}:"


def main():
    parser = argparse.ArgumentParser(description="Scan ore deposits and save coordinates")
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name or ID")
    parser.add_argument("--radius", type=int, default=1000, help="Scan radius (m)")
    parser.add_argument("--cell_size", type=float, default=10.0, help="Voxel cell size")
    parser.add_argument("--bbox_y", type=int, default=1000, help="Bounding box Y size")
    parser.add_argument("--cluster_radius", type=float, default=50.0, help="Clustering radius (m)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--full_scan", action="store_true", help="Also do full voxel geometry scan")
    args = parser.parse_args()

    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{DATA_DIR}/ore_scan_{ts}.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"Connecting to grid: {args.grid}")
    grid = prepare_grid(args.grid)
    print(f"  Grid: {grid.name} (id={grid.grid_id})")

    own_position = get_own_position(grid)
    print(f"  Ship position: {own_position}")

    radar = grid.get_first_device(OreDetectorDevice)
    if not radar:
        print("ERROR: No Ore Detector found on grid!")
        close(grid)
        return
    print(f"  Radar: {radar.name} (id={radar.device_id})")

    radar.cancel_scan()
    time.sleep(0.3)

    # Ore-only scan — critical: ore_only=True avoids 256-cell truncation
    print(f"\n{'='*60}")
    print(f"  ORE SCAN (ore_only=True, radius={args.radius}m)")
    print(f"{'='*60}")

    ore_ctrl = RadarController(
        radar, ore_only=True, radius=args.radius,
        cell_size=args.cell_size, boundingBoxY=args.bbox_y,
    )

    t0 = time.time()
    ore_solid, ore_meta, ore_contacts, ore_cells = ore_ctrl.scan_voxels()
    ore_scan_time = time.time() - t0

    # Grab raw radar data
    radar.update()
    raw_radar = (radar.telemetry or {}).get("radar", {})
    all_ore_cells = raw_radar.get("oreCells", [])
    ore_cell_count = raw_radar.get("oreCellCount", 0)
    ore_truncated = raw_radar.get("oreCellsTruncated", 0)

    effective_ore = all_ore_cells if all_ore_cells else (ore_cells or [])
    valuable = [c for c in effective_ore if (c.get("ore") or c.get("material")) not in ("Stone", "", None)]

    print(f"\n  Scan time: {ore_scan_time:.1f}s")
    print(f"  oreCellCount: {ore_cell_count}, transmitted: {len(all_ore_cells)}, truncated: {ore_truncated}")

    type_counts = Counter()
    for cell in effective_ore:
        ore = cell.get("ore") or cell.get("material") or "?"
        type_counts[ore] += 1
    print(f"  Ore types: {dict(type_counts.most_common())}")
    print(f"  Valuable deposits: {len(valuable)}")

    # Optional full voxel scan
    if args.full_scan:
        print(f"\n{'='*60}")
        print(f"  FULL VOXEL SCAN (radius=300m)")
        print(f"{'='*60}")
        radar.cancel_scan()
        time.sleep(0.3)
        voxel_ctrl = RadarController(radar, ore_only=False, radius=300, cell_size=args.cell_size, fullSolidScan=True)
        vox_solid, vox_meta, _, _ = voxel_ctrl.scan_voxels()
        print(f"  Solid voxels: {len(vox_solid) if vox_solid else 0}")

    # Process results
    ore_entries = []
    for cell in valuable:
        ore = cell.get("ore") or cell.get("material") or "Unknown"
        pos = cell.get("position", [0, 0, 0])
        entry = {"ore_type": ore, "position": [round(p, 1) for p in pos], "content": cell.get("content")}
        if own_position:
            entry["distance_from_ship"] = round(math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, own_position))), 1)
        ore_entries.append(entry)

    clusters = cluster_ore_deposits(valuable, cluster_radius=args.cluster_radius)

    ore_summary = {}
    for entry in ore_entries:
        t = entry["ore_type"]
        ore_summary.setdefault(t, {"count": 0, "min_dist": float("inf"), "max_content": 0})
        ore_summary[t]["count"] += 1
        if "distance_from_ship" in entry:
            ore_summary[t]["min_dist"] = min(ore_summary[t]["min_dist"], entry["distance_from_ship"])
        if entry.get("content"):
            ore_summary[t]["max_content"] = max(ore_summary[t]["max_content"], entry["content"])

    print(f"\n  Ore summary:")
    for ore_type, info in sorted(ore_summary.items()):
        dist = f", closest: {info['min_dist']:.0f}m" if info["min_dist"] < float("inf") else ""
        print(f"    {ore_type}: {info['count']} deposits, max_content={info['max_content']}{dist}")

    print(f"\n  Clusters ({len(clusters)}):")
    for i, cl in enumerate(clusters):
        dist = ""
        if own_position:
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(cl["center"], own_position)))
            dist = f", {d:.0f}m"
        gps = gps_string(f"{cl['ore_type']}_{i+1}", cl["center"])
        print(f"    {i+1}. {cl['ore_type']}: {cl['deposit_count']} deposits, spread={cl['spread_m']}m{dist}")
        print(f"       {gps}")

    gps_markers = [gps_string(f"{cl['ore_type']}_{i+1}", cl["center"]) for i, cl in enumerate(clusters)]

    scan_result = {
        "scan_time": datetime.now().isoformat(),
        "grid": {"name": grid.name, "id": grid.grid_id},
        "ship_position": own_position,
        "scan_config": {"radius": args.radius, "cell_size": args.cell_size, "bbox_y": args.bbox_y, "ore_only": True},
        "scan_stats": {
            "ore_scan_time_s": round(ore_scan_time, 1),
            "total_deposits": len(ore_entries),
            "ore_cell_count": ore_cell_count,
            "ore_cells_truncated": ore_truncated,
        },
        "ore_summary": {k: {"count": v["count"], "closest_m": round(v["min_dist"], 1) if v["min_dist"] < float("inf") else None, "max_content": v["max_content"]} for k, v in ore_summary.items()},
        "clusters": clusters,
        "gps_markers": gps_markers,
        "all_deposits": ore_entries,
    }

    with open(output_path, "w") as f:
        json.dump(scan_result, f, indent=2, default=str)
    latest_path = os.path.join(os.path.dirname(output_path), "ore_latest.json")
    with open(latest_path, "w") as f:
        json.dump(scan_result, f, indent=2, default=str)

    print(f"\n  SAVED: {output_path}")
    print(f"  LATEST: {latest_path}")

    if gps_markers:
        print(f"\n  GPS markers (copy-paste to SE):")
        for gps in gps_markers:
            print(f"    {gps}")

    close(grid)


if __name__ == "__main__":
    main()
