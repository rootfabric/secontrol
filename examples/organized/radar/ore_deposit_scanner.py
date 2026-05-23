"""
Ore Deposit Scanner — сканирует ресурсы на астероиде и сохраняет координаты.
Результат: JSON-файл с месторождениями, готовый для постройки базы добычи.

Использует ore_only=True для сканирования — пропускает Stone,
не забивает буфер truncation (256 cell limit).

Usage:
    python ore_deposit_scanner.py                     # skynet-baza0, default
    python ore_deposit_scanner.py --grid DroneBase    # другая сетка
    python ore_deposit_scanner.py --radius 500        # меньший радиус
    python ore_deposit_scanner.py --full_scan          # + полная геометрия вокселей
"""

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position

ORE_DB_PATH = Path.home() / "hermeswebui" / "se-data" / "ore_database.jsonl"


def append_ore_scan_to_db(scan_result: dict) -> None:
    """Append scan result to ore database (JSONL)."""
    ORE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(scan_result, default=str)
    with open(ORE_DB_PATH, "a") as f:
        f.write(line + "\n")
    print(f"  DB: appended to {ORE_DB_PATH}")


def get_nearest_asteroid(grid) -> dict | None:
    """Find the nearest asteroid from asteroidIndex."""
    from secontrol.devices.ore_detector_device import OreDetectorDevice
    radar = grid.get_first_device(OreDetectorDevice)
    if not radar:
        return None
    radar.update()
    tel = radar.telemetry or {}
    ai = tel.get("asteroidIndex", {})
    if not ai.get("ready"):
        return None
    items = ai.get("items", [])
    if not items:
        return None
    ship = None
    for dev_type in ["cockpit", "remote_control"]:
        devices = grid.find_devices_by_type(dev_type)
        if devices:
            devices[0].update()
            pos = get_world_position(devices[0])
            if pos:
                ship = list(pos)
                break
    if not ship:
        return None
    nearest = None
    min_dist = float("inf")
    for ast in items:
        d = ast.get("distance", float("inf"))
        if d < min_dist:
            min_dist = d
            nearest = ast
    return nearest


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
    """
    Group nearby ore deposits into clusters.
    Returns: list of {ore_type, center, count, positions, bounding_box, spread_m}
    """
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
                "bounding_box": {
                    "min": [round(m, 1) for m in mins],
                    "max": [round(M, 1) for M in maxs],
                },
                "spread_m": round(math.sqrt(sum((M - m) ** 2 for m, M in zip(mins, maxs))), 1),
            })

    clusters.sort(key=lambda c: c["deposit_count"], reverse=True)
    return clusters


def gps_string(name, pos, color="#FF8800"):
    """Format GPS marker for SE copy-paste."""
    return f"GPS:{name}:{pos[0]}:{pos[1]}:{pos[2]}:{color}:"


def find_nearest_ore(scan_path, ore_type, from_position=None, n=1):
    """Find N nearest deposits of a given ore type from saved scan data.

    Args:
        scan_path: Path to ore scan JSON (or None → ore_latest.json)
        ore_type: Ore name to search (case-insensitive): "Gold", "Platinum", "Iron", etc.
        from_position: [x,y,z] to measure distance from. If None, uses ship_position from scan.
        n: Number of results to return (default 1).

    Returns:
        List of dicts: [{ore_type, position, distance, gps, cluster}, ...] sorted by distance.
        Empty list if ore_type not found.
    """
    if scan_path is None:
        scan_path = str(Path.home() / "hermeswebui" / "se-data" / "scans" / "ore_latest.json")

    with open(scan_path) as f:
        data = json.load(f)

    origin = from_position or data.get("ship_position")
    if not origin:
        raise ValueError("No from_position and no ship_position in scan data")

    target = ore_type.lower()
    matches = []

    # Search clusters first (preferred — grouped deposits)
    for cl in data.get("clusters", []):
        if cl["ore_type"].lower() != target:
            continue
        c = cl["center"]
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(c, origin)))
        matches.append({
            "ore_type": cl["ore_type"],
            "position": c,
            "distance": round(d, 1),
            "gps": gps_string(f"{cl['ore_type']}", c),
            "deposits": cl["deposit_count"],
            "spread_m": cl["spread_m"],
            "source": "cluster",
        })

    # Also search individual deposits
    for dep in data.get("all_deposits", []):
        if dep["ore_type"].lower() != target:
            continue
        pos = dep["position"]
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, origin)))
        matches.append({
            "ore_type": dep["ore_type"],
            "position": pos,
            "distance": round(d, 1),
            "gps": gps_string(dep["ore_type"], pos),
            "content": dep.get("content"),
            "source": "deposit",
        })

    matches.sort(key=lambda m: m["distance"])
    return matches[:n]


def load_scan(path=None):
    """Load saved scan data. Returns parsed JSON dict."""
    path = path or str(Path.home() / "hermeswebui" / "se-data" / "scans" / "ore_latest.json")
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Scan ore deposits and save coordinates")
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name or ID")
    parser.add_argument("--radius", type=int, default=1000, help="Scan radius (m)")
    parser.add_argument("--cell_size", type=float, default=10.0, help="Voxel cell size")
    parser.add_argument("--bbox_y", type=int, default=1000, help="Bounding box Y size")
    parser.add_argument("--cluster_radius", type=float, default=50.0, help="Clustering radius (m)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--full_scan", action="store_true", help="Also do full voxel geometry scan")
    parser.add_argument("--find", default=None, metavar="ORE", help="Find nearest deposit of ORE from latest scan (e.g. Gold, Platinum)")
    parser.add_argument("--find_n", type=int, default=3, help="Number of results for --find")
    args = parser.parse_args()

    # ── Find mode (no scan needed) ──
    if args.find:
        results = find_nearest_ore(None, args.find, n=args.find_n)
        if not results:
            print(f"No '{args.find}' deposits found in latest scan.")
            return
        print(f"Nearest {args.find} deposits:")
        for i, r in enumerate(results):
            label = f"cluster ({r['deposits']} deposits)" if r["source"] == "cluster" else f"deposit (content={r.get('content', '?')})"
            print(f"  {i+1}. {r['distance']}m — {label}")
            print(f"     {r['gps']}")
        return

    # Output path — cross-platform, outside git repo
    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        scan_dir = Path.home() / "hermeswebui" / "se-data" / "scans"
        scan_dir.mkdir(parents=True, exist_ok=True)
        output_path = scan_dir / f"ore_scan_{ts}.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Connect
    print(f"Connecting to grid: {args.grid}")
    grid = prepare_grid(args.grid)
    grid_id = grid.grid_id
    grid_name = grid.name
    print(f"  Grid: {grid_name} (id={grid_id})")

    own_position = get_own_position(grid)
    print(f"  Ship position: {own_position}")

    radar = grid.get_first_device(OreDetectorDevice)
    if not radar:
        print("ERROR: No Ore Detector found on grid!")
        close(grid)
        return
    print(f"  Radar: {radar.name} (id={radar.device_id})")

    # Cancel previous
    radar.cancel_scan()
    time.sleep(0.3)

    # ── Ore-only scan (fast, no Stone truncation) ──
    print(f"\n{'='*60}")
    print(f"  ORE SCAN (ore_only=True, radius={args.radius}m)")
    print(f"{'='*60}")

    ore_ctrl = RadarController(
        radar,
        ore_only=True,
        radius=args.radius,
        cell_size=args.cell_size,
        boundingBoxY=args.bbox_y,
    )

    t0 = time.time()
    ore_solid, ore_meta, ore_contacts, ore_cells = ore_ctrl.scan_voxels()
    ore_scan_time = time.time() - t0

    # Also grab raw radar data for full oreCells
    radar.update()
    tel = radar.telemetry or {}
    raw_radar = tel.get("radar", {})
    all_ore_cells = raw_radar.get("oreCells", [])
    ore_cell_count = raw_radar.get("oreCellCount", 0)
    ore_truncated = raw_radar.get("oreCellsTruncated", 0)

    print(f"\n  Scan time: {ore_scan_time:.1f}s")
    print(f"  oreCellCount: {ore_cell_count}")
    print(f"  oreCells transmitted: {len(all_ore_cells)}")
    print(f"  oreCells truncated: {ore_truncated}")

    # Use all_ore_cells if available, fall back to ore_cells
    effective_ore = all_ore_cells if all_ore_cells else (ore_cells or [])
    valuable = [c for c in effective_ore if (c.get("ore") or c.get("material")) not in ("Stone", "", None)]

    type_counts = Counter()
    for cell in effective_ore:
        ore = cell.get("ore") or cell.get("material") or "?"
        type_counts[ore] += 1

    print(f"\n  Ore types: {dict(type_counts.most_common())}")
    print(f"  Valuable deposits: {len(valuable)}")

    # ── Optional: Full voxel scan ──
    vox_solid = []
    vox_meta = {}
    if args.full_scan:
        print(f"\n{'='*60}")
        print(f"  FULL VOXEL SCAN (radius=300m)")
        print(f"{'='*60}")
        radar.cancel_scan()
        time.sleep(0.3)

        voxel_ctrl = RadarController(
            radar, ore_only=False, radius=300, cell_size=args.cell_size, fullSolidScan=True
        )
        t0 = time.time()
        vox_solid, vox_meta, _, _ = voxel_ctrl.scan_voxels()
        vox_time = time.time() - t0
        print(f"  Scan time: {vox_time:.1f}s")
        print(f"  Solid voxels: {len(vox_solid) if vox_solid else 0}")

    # ── Process results ──
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")

    # Ore entries with distances
    ore_entries = []
    for cell in valuable:
        ore = cell.get("ore") or cell.get("material") or "Unknown"
        pos = cell.get("position", [0, 0, 0])
        entry = {
            "ore_type": ore,
            "position": [round(p, 1) for p in pos],
            "content": cell.get("content"),
        }
        if own_position:
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, own_position)))
            entry["distance_from_ship"] = round(d, 1)
        ore_entries.append(entry)

    # Cluster
    clusters = cluster_ore_deposits(valuable, cluster_radius=args.cluster_radius)

    # Summary
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
        dist_str = f", closest: {info['min_dist']:.0f}m" if info["min_dist"] < float("inf") else ""
        print(f"    {ore_type}: {info['count']} deposits, max_content={info['max_content']}{dist_str}")

    print(f"\n  Clusters ({len(clusters)}):")
    for i, cl in enumerate(clusters):
        dist_str = ""
        if own_position:
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(cl["center"], own_position)))
            dist_str = f", {d:.0f}m from ship"
        gps = gps_string(f"{cl['ore_type']}_{i+1}", cl["center"])
        print(f"    {i+1}. {cl['ore_type']}: {cl['deposit_count']} deposits, "
              f"spread={cl['spread_m']}m{dist_str}")
        print(f"       {gps}")

    # GPS markers
    gps_markers = []
    for i, cl in enumerate(clusters):
        c = cl["center"]
        gps_markers.append(gps_string(f"{cl['ore_type']}_{i+1}", c))

    # ── Find nearest asteroid for context ──
    asteroid = get_nearest_asteroid(grid)
    asteroid_info = None
    if asteroid:
        asteroid_info = {
            "name": asteroid.get("name"),
            "center": asteroid.get("center"),
            "distance": asteroid.get("distance"),
            "surfaceDistance": asteroid.get("surfaceDistance"),
            "approxRadius": asteroid.get("approxRadius"),
            "seed": asteroid.get("seed"),
        }

    # ── Build output ──
    scan_result = {
        "scan_time": datetime.now().isoformat(),
        "grid": {"name": grid_name, "id": grid_id},
        "ship_position": own_position,
        "asteroid": asteroid_info,
        "scan_config": {
            "radius": args.radius,
            "cell_size": args.cell_size,
            "bbox_y": args.bbox_y,
            "ore_only": True,
            "cluster_radius": args.cluster_radius,
        },
        "scan_stats": {
            "ore_scan_time_s": round(ore_scan_time, 1),
            "total_deposits": len(ore_entries),
            "ore_cell_count": ore_cell_count,
            "ore_cells_transmitted": len(all_ore_cells),
            "ore_cells_truncated": ore_truncated,
        },
        "ore_summary": {
            k: {
                "count": v["count"],
                "closest_m": round(v["min_dist"], 1) if v["min_dist"] < float("inf") else None,
                "max_content": v["max_content"],
            }
            for k, v in ore_summary.items()
        },
        "clusters": clusters,
        "gps_markers": gps_markers,
        "all_deposits": ore_entries,
    }

    # Add solid voxel data if full scan was done
    if args.full_scan and vox_solid:
        scan_result["voxel_scan"] = {
            "scan_time_s": round(vox_time, 1),
            "solid_count": len(vox_solid),
            "metadata": {
                "size": vox_meta.get("size"),
                "cell_size": vox_meta.get("cellSize"),
                "origin": vox_meta.get("origin"),
            },
        }
        solid_path = output_path.replace(".json", "_solid.json")
        with open(solid_path, "w") as f:
            json.dump({
                "solid_points": [[round(p, 1) for p in pt] for pt in vox_solid],
                "metadata": vox_meta,
            }, f)
        scan_result["voxel_scan"]["solid_file"] = solid_path
        print(f"\n  Solid voxels saved to: {solid_path}")

    # ── Save ──
    output_path = Path(output_path)
    with open(output_path, "w") as f:
        json.dump(scan_result, f, indent=2, default=str)

    latest_path = output_path.parent / "ore_latest.json"
    with open(latest_path, "w") as f:
        json.dump(scan_result, f, indent=2, default=str)

    append_ore_scan_to_db(scan_result)

    print(f"\n{'='*60}")
    print(f"  SAVED: {output_path}")
    print(f"  LATEST: {latest_path}")
    print(f"{'='*60}")

    # GPS for copy-paste
    if gps_markers:
        print(f"\n  GPS markers (copy-paste to SE):")
        for gps in gps_markers:
            print(f"    {gps}")

    close(grid)
    print("\nDone!")


if __name__ == "__main__":
    main()
