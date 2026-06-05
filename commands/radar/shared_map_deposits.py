"""
Show ore deposits from SharedMapController sorted by distance from grid.

Loads all known ore deposits, gets current grid position from RC/cockpit,
and outputs them sorted by distance (nearest first or farthest first).

Usage:
    python shared_map_deposits.py                         # nearest first
    python shared_map_deposits.py --grid skynet-baza0     # specify grid
    python shared_map_deposits.py --material Platinum     # filter by ore
    python shared_map_deposits.py --order farthest        # farthest first
    python shared_map_deposits.py --clusters              # group into clusters
    python shared_map_deposits.py --gps                   # include GPS markers
    python shared_map_deposits.py --limit 5               # top N results

Agent output format:
    Grid: skynet-baza0 @ (-50500, 146600, -137800)
    3 known ore deposits:
      1. Platinum  @ (-56810.0, 146506.1, -134196.9)  —  7,263m
      2. Gold      @ (-50600.0, 146600.0, -137700.0)  —    120m
      3. Silver    @ (-50400.0, 146500.0, -137900.0)  —    180m

For agent use — importable:
    from examples.organized.radar.shared_map.shared_map_deposits import get_deposits_sorted
    deposits = get_deposits_sorted(owner_id="...", from_position=(x, y, z), material="Platinum")
    for dep in deposits:
        print(f"{dep['material']} @ {dep['position']} \u2014 {dep['distance_m']}m")
"""
import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

from secontrol.common import resolve_owner_id
from secontrol.controllers import SharedMapController
from secontrol.controllers.shared_map_controller import OreHit


def get_grid_position(grid) -> Optional[Tuple[float, float, float]]:
    """Get grid's world position from cockpit or remote control."""
    for dev_type in ["cockpit", "remote_control"]:
        devices = grid.find_devices_by_type(dev_type)
        if devices:
            devices[0].update()
            from secontrol.tools.navigation_tools import get_world_position
            pos = get_world_position(devices[0])
            if pos:
                return (pos[0], pos[1], pos[2])
    return None


def gps_string(name: str, pos, color: str = "#FF8800") -> str:
    """Format GPS marker for SE copy-paste."""
    return f"GPS:{name}:{pos[0]}:{pos[1]}:{pos[2]}:{color}:"


def cluster_ores(ores: List[OreHit], cluster_radius: float = 50.0):
    """Group nearby ore deposits into spatial clusters by material."""
    from collections import defaultdict
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

            results.append({
                "material": material,
                "center": (cx, cy, cz),
                "count": len(cluster_pts),
            })
    return results


def get_deposits_sorted(
    owner_id: Optional[str] = None,
    from_position: Optional[Tuple[float, float, float]] = None,
    material: Optional[str] = None,
    storage_backend: str = "redis",
    chunk_size: float = 100.0,
    order: str = "nearest",
    cluster: bool = False,
    cluster_radius: float = 50.0,
) -> List[Dict[str, Any]]:
    """Return ore deposits sorted by distance from position.

    Args:
        owner_id: SE owner ID (auto-resolved if None)
        from_position: (x,y,z) origin. If None, uses grid's current position.
        material: Filter by ore type (e.g. "Platinum"). Case-insensitive.
        storage_backend: "redis" or "sqlite"
        chunk_size: SharedMap chunk size
        order: "nearest" or "farthest"
        cluster: Group deposits into clusters
        cluster_radius: Cluster merge radius in meters

    Returns:
        List of dicts with keys: material, position, distance_m, (count if cluster)
    """
    owner_id = owner_id or resolve_owner_id()

    # 1. Try SharedMapController first
    ctrl = SharedMapController(
        owner_id=owner_id,
        chunk_size=chunk_size,
        storage_backend=storage_backend,
    )
    ctrl.load()

    ores = ctrl.get_known_ores(material=material)
    origin = from_position or _get_known_position(ctrl)

    if ores and origin:
        if cluster:
            raw_clusters = cluster_ores(ores, cluster_radius=cluster_radius)
            if material:
                raw_clusters = [c for c in raw_clusters if c["material"].lower() == material.lower()]
            results = []
            for cl in raw_clusters:
                d = math.sqrt(sum((a - b) ** 2 for a, b in zip(cl["center"], origin)))
                results.append({
                    "material": cl["material"],
                    "position": cl["center"],
                    "distance_m": round(d, 1),
                    "count": cl["count"],
                    "cluster": True,
                    "source": "shared_map",
                })
            results.sort(key=lambda r: r["distance_m"], reverse=(order == "farthest"))
            return results
        else:
            results = []
            for ore in ores:
                d = math.sqrt(sum((a - b) ** 2 for a, b in zip(ore.position, origin)))
                results.append({
                    "material": ore.material,
                    "position": ore.position,
                    "distance_m": round(d, 1),
                    "content": ore.content,
                    "cluster": False,
                    "source": "shared_map",
                })
            results.sort(key=lambda r: r["distance_m"], reverse=(order == "farthest"))
            return results

    # 2. Fallback: JSON database files (ore_database.jsonl, ore_latest.json)
    json_data = _load_from_json_db(material=material)
    if json_data:
        return _json_to_deposits(json_data, origin, material, order, cluster)

    return []


def _load_from_json_db(
    material: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Search ore_database.jsonl and ore_latest.json for deposits.

    Returns parsed scan result dict (with 'clusters' and 'all_deposits')
    if the requested material is found, else None.
    """
    db_paths = [
        Path.home() / "hermeswebui" / "se-data" / "ore_database.jsonl",
        Path.home() / "hermeswebui" / "se-data" / "scans" / "ore_latest.json",
    ]
    for path in db_paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if path.suffix == ".jsonl":
            for line in text.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if material:
                    for c in entry.get("clusters", []):
                        if material.lower() in c.get("ore_type", "").lower():
                            return entry
                elif entry.get("clusters"):
                    return entry
        else:
            try:
                entry = json.loads(text)
            except json.JSONDecodeError:
                continue
            if material:
                for c in entry.get("clusters", []):
                    if material.lower() in c.get("ore_type", "").lower():
                        return entry
            elif entry.get("clusters"):
                return entry
    return None


def _json_to_deposits(
    data: Dict[str, Any],
    origin: Optional[Tuple[float, float, float]],
    material: Optional[str],
    order: str,
    cluster: bool,
) -> List[Dict[str, Any]]:
    """Convert JSON scan result to deposit list sorted by distance."""
    results = []

    if cluster or not origin:
        for c in data.get("clusters", []):
            if material and material.lower() not in c["ore_type"].lower():
                continue
            pos = tuple(c["center"])
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, origin))) if origin else -1
            results.append({
                "material": c["ore_type"],
                "position": pos,
                "distance_m": round(d, 1),
                "count": c["deposit_count"],
                "cluster": True,
            })
    else:
        for dep in data.get("all_deposits", []):
            if material and material.lower() not in dep["ore_type"].lower():
                continue
            pos = tuple(dep["position"])
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, origin)))
            results.append({
                "material": dep["ore_type"],
                "position": pos,
                "distance_m": round(d, 1),
                "content": dep.get("content"),
                "cluster": False,
            })

    if origin:
        results.sort(key=lambda r: r["distance_m"], reverse=(order == "farthest"))
    return results


def _get_known_position(ctrl: SharedMapController) -> Optional[Tuple[float, float, float]]:
    """Try to get position from shared map metadata."""
    if ctrl.data.visited:
        return ctrl.data.visited[-1]
    md = ctrl.data.metadata
    if md:
        last_radar = md.get("last_radar", {})
        if last_radar:
            origin = last_radar.get("origin")
            if origin:
                return tuple(origin[:3])
    return None


def _deposits_without_distance(ores, cluster, cluster_radius):
    """Fallback when no position is known: return unsorted."""
    if cluster:
        raw = cluster_ores(ores, cluster_radius)
        return [{"material": c["material"], "position": c["center"], "distance_m": -1, "count": c["count"], "cluster": True} for c in raw]
    return [{"material": o.material, "position": o.position, "distance_m": -1, "content": o.content, "cluster": False} for o in ores]


_ORE_COLORS = {
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


def _color(material: str) -> str:
    return _ORE_COLORS.get(material.lower(), "#FF8800")


def show_deposits(args):
    owner_id = args.owner_id or resolve_owner_id()

    # Get grid position if needed
    from_position = None
    grid = None
    if args.grid:
        from secontrol.common import prepare_grid
        grid = prepare_grid(args.grid)
        if not args.owner_id:
            owner_id = grid.owner_id
        from_position = get_grid_position(grid)
        if from_position:
            print(f"Grid: {args.grid} @ ({from_position[0]:.0f}, {from_position[1]:.0f}, {from_position[2]:.0f})")
        else:
            print(f"Grid: {args.grid} (position unknown)")
            sys.stdout.flush()

    deposits = get_deposits_sorted(
        owner_id=owner_id,
        from_position=from_position,
        material=args.material,
        storage_backend=args.storage,
        chunk_size=args.chunk_size,
        order=args.order,
        cluster=args.clusters,
        cluster_radius=args.cluster_radius,
    )

    if not deposits:
        print("No ore deposits found.")
        print("Try: run a radar scan first (ore_deposit_scanner.py --grid ...)")
        return

    order_label = "farthest" if args.order == "farthest" else "nearest"
    print(f"{len(deposits)} deposits (sorted by {order_label}):")

    for i, dep in enumerate(deposits):
        dist_str = f"{dep['distance_m']:>8,.0f}m" if dep['distance_m'] >= 0 else "  unknown"

        if dep.get("cluster"):
            print(f"  {i+1}. {dep['material']}: {dep['count']} deposits  @ {dep['position']}  \u2014 {dist_str}")
        else:
            c = dep.get("content")
            content_str = f", content={c}" if c is not None else ""
            print(f"  {i+1}. {dep['material']}{content_str} @ {dep['position']}  \u2014 {dist_str}")

    if args.gps:
        print(f"\nGPS markers:")
        for i, dep in enumerate(deposits):
            if args.limit and i >= args.limit:
                break
            pos = dep["position"]
            label = dep["material"]
            if dep.get("cluster"):
                label = f"{label}_cluster_{i+1}"
            else:
                label = f"{label}_{i+1}"
            gps = gps_string(label, pos, _color(dep["material"]))
            print(f"  {gps}")


def main():
    parser = argparse.ArgumentParser(description="Show ore deposits sorted by distance from grid")
    parser.add_argument("--grid", default=None, help="Grid name to get position from")
    parser.add_argument("--material", default=None, help="Filter by ore type (Gold, Platinum, etc.)")
    parser.add_argument("--owner-id", default=None, help="Owner ID (auto-resolved if not set)")
    parser.add_argument("--storage", default="redis", choices=["redis", "sqlite"], help="Storage backend")
    parser.add_argument("--chunk-size", type=float, default=100.0, help="Map chunk size")
    parser.add_argument("--order", default="nearest", choices=["nearest", "farthest"], help="Sort order")
    parser.add_argument("--clusters", action="store_true", help="Group deposits into clusters")
    parser.add_argument("--cluster-radius", type=float, default=50.0, help="Cluster merge radius (m)")
    parser.add_argument("--limit", type=int, default=0, help="Max results (0 = unlimited)")
    parser.add_argument("--gps", action="store_true", help="Include GPS markers")
    args = parser.parse_args()

    show_deposits(args)


if __name__ == "__main__":
    main()
