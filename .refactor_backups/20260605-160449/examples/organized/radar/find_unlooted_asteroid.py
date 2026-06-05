"""
Find the nearest unscanned asteroid from the grid.

Loads visible asteroids from the ore detector's asteroid index,
loads known ore deposits from SharedMapController (or JSON fallback),
determines which asteroids have been surveyed (have ore data within their radius),
and recommends the closest unexplored one.

Usage:
    python find_unlooted_asteroid.py                         # default grid
    python find_unlooted_asteroid.py --grid skynet-baza0     # specify grid
    python find_unlooted_asteroid.py --radius 50000          # search radius
    python find_unlooted_asteroid.py --gps                   # GPS markers
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from secontrol.common import close, prepare_grid, resolve_owner_id
from secontrol.controllers import SharedMapController
from secontrol.controllers.shared_map_controller import OreHit
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.tools.navigation_tools import get_world_position


def request_asteroids(
    radar: OreDetectorDevice,
    *,
    radius: float = 50_000,
    limit: int = 320,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Request asteroid index and wait for fresh telemetry."""
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_rev = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command({
        "cmd": "asteroids",
        "targetId": int(radar.device_id),
        "state": {
            "radius": float(radius),
            "limit": int(limit),
            "includePlanets": False,
        },
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        ai = telemetry.get("asteroidIndex")
        if isinstance(ai, dict) and ai.get("ready"):
            rev = ai.get("revision")
            if rev != previous_rev:
                return ai
    return None


def get_grid_position(grid) -> Optional[Tuple[float, float, float]]:
    """Get grid world position from cockpit or remote control."""
    for dev_type in ["cockpit", "remote_control"]:
        devices = grid.find_devices_by_type(dev_type)
        if devices:
            devices[0].update()
            pos = get_world_position(devices[0])
            if pos:
                return (pos[0], pos[1], pos[2])
    return None


def load_known_ores(
    owner_id: str,
    material: Optional[str] = None,
) -> List[OreHit]:
    """Load ore deposits from SharedMapController with JSON fallback."""
    ctrl = SharedMapController(owner_id=owner_id, storage_backend="redis")
    ctrl.load()
    ores = ctrl.get_known_ores(material=material)
    if ores:
        return ores

    # Fallback: JSON database
    json_paths = [
        Path.home() / "hermeswebui" / "se-data" / "ore_database.jsonl",
        Path.home() / "hermeswebui" / "se-data" / "scans" / "ore_latest.json",
    ]
    for path in json_paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        results: List[OreHit] = []
        if path.suffix == ".jsonl":
            for line in text.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for dep in entry.get("all_deposits", []):
                    ore_name = dep.get("ore_type", "")
                    if material and material.lower() not in ore_name.lower():
                        continue
                    pos = dep.get("position")
                    if pos and len(pos) == 3:
                        results.append(OreHit(material=ore_name, position=tuple(pos), content=dep.get("content")))
        else:
            try:
                entry = json.loads(text)
            except json.JSONDecodeError:
                continue
            for dep in entry.get("all_deposits", []):
                ore_name = dep.get("ore_type", "")
                if material and material.lower() not in ore_name.lower():
                    continue
                pos = dep.get("position")
                if pos and len(pos) == 3:
                    results.append(OreHit(material=ore_name, position=tuple(pos), content=dep.get("content")))

        if results:
            return results
    return []


def point_in_asteroid(
    point: Tuple[float, float, float],
    center: List[float],
    approx_radius: float,
    margin: float = 1.5,
) -> bool:
    """Check if a point is within an asteroid's approximate radius (with margin)."""
    if not center or len(center) < 3:
        return False
    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(point, center[:3])))
    return d <= approx_radius * margin


def classify_asteroids(
    asteroids: List[Dict[str, Any]],
    ores: List[OreHit],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split asteroids into explored (have ore data) and unexplored.

    Returns (explored_list, unexplored_list), each item has asteroid dict
    plus 'ore_types' key with set of found ore types.
    """
    explored = []
    unexplored = []

    for ast in asteroids:
        center = ast.get("center", [])
        radius = ast.get("approxRadius", 500)
        if not center or len(center) < 3:
            unexplored.append({**ast, "ore_types": set()})
            continue

        # Find ores within this asteroid's radius
        ast_ores: Dict[str, int] = defaultdict(int)
        for ore in ores:
            if point_in_asteroid(ore.position, center, radius):
                ast_ores[ore.material] += 1

        entry = {**ast, "ore_types": dict(ast_ores)}
        if ast_ores:
            explored.append(entry)
        else:
            unexplored.append(entry)

    return explored, unexplored


def fmt_dist(value: Any) -> str:
    try:
        return f"{float(value):,.0f}m"
    except (TypeError, ValueError):
        return "N/A"


def gps_string(name: str, pos, color: str = "#FF8800") -> str:
    return f"GPS:{name}:{pos[0]}:{pos[1]}:{pos[2]}:{color}:"


def print_report(
    grid_name: str,
    grid_pos: Optional[Tuple[float, float, float]],
    explored: List[Dict[str, Any]],
    unexplored: List[Dict[str, Any]],
    show_gps: bool,
) -> None:
    total = len(explored) + len(unexplored)

    if grid_pos:
        print(f"Grid: {grid_name} @ ({grid_pos[0]:.0f}, {grid_pos[1]:.0f}, {grid_pos[2]:.0f})")
    else:
        print(f"Grid: {grid_name} (position unknown)")
    print(f"Visible asteroids: {total}  |  Explored: {len(explored)}  |  Unexplored: {len(unexplored)}")
    print()

    # ── Explored asteroids ──
    if explored:
        print(f"{'='*70}")
        print(f"  EXPLORED ASTEROIDS ({len(explored)}) — have ore data")
        print(f"{'='*70}")
        for i, ast in enumerate(explored):
            name = ast.get("name") or "<unnamed>"
            dist = fmt_dist(ast.get("distance"))
            radius = fmt_dist(ast.get("approxRadius"))
            ore_types = ast.get("ore_types", {})
            ore_str = ", ".join(f"{ore}({cnt})" for ore, cnt in sorted(ore_types.items()))
            print(f"  {i+1}. {name}")
            print(f"     Distance: {dist}  |  Radius: {radius}")
            print(f"     Ores: {ore_str}")
            if show_gps:
                center = ast.get("center", [])
                if len(center) >= 3:
                    print(f"     {gps_string(name, center, '#00FF88')}")
        print()

    # ── Unexplored asteroids ──
    if unexplored:
        print(f"{'='*70}")
        print(f"  UNEXPLORED ASTEROIDS ({len(unexplored)}) — no ore data")
        print(f"{'='*70}")
        for i, ast in enumerate(unexplored):
            name = ast.get("name") or "<unnamed>"
            dist = fmt_dist(ast.get("distance"))
            radius = fmt_dist(ast.get("approxRadius"))
            surface = fmt_dist(ast.get("surfaceDistance"))
            print(f"  {i+1}. {name}")
            print(f"     Distance: {dist}  |  Surface: {surface}  |  Radius: {radius}")
            if show_gps:
                center = ast.get("center", [])
                if len(center) >= 3:
                    print(f"     {gps_string(name, center, '#FF8800')}")
        print()

    # ── Recommendation ──
    if unexplored:
        best = unexplored[0]
        name = best.get("name") or "<unnamed>"
        dist = fmt_dist(best.get("distance"))
        center = best.get("center", [])
        print(f"{'='*70}")
        print(f"  RECOMMENDATION: fly to unexplored asteroid")
        print(f"{'='*70}")
        print(f"  {name}  —  {dist} away")
        if len(center) >= 3:
            print(f"  Center: ({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})")
            print(f"  {gps_string(name, center, '#FFFF00')}")
        print()
    elif explored:
        print("All visible asteroids have been explored!")
    else:
        print("No asteroids found. Try increasing --radius.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find the nearest unscanned asteroid from the grid"
    )
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name")
    parser.add_argument("--radius", type=float, default=50_000, help="Asteroid search radius (m)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Asteroid index timeout (s)")
    parser.add_argument("--gps", action="store_true", help="Show GPS markers")
    parser.add_argument("--owner-id", default=None, help="Owner ID for SharedMap")
    args = parser.parse_args()

    # Connect
    grid = prepare_grid(args.grid)
    grid_name = grid.name

    try:
        # Get grid position
        grid_pos = get_grid_position(grid)

        # Find radar and request asteroids
        radar = grid.get_first_device(OreDetectorDevice)
        if not radar:
            print("ERROR: No Ore Detector found on grid!")
            return

        print(f"Requesting asteroid index (radius={args.radius:,.0f}m)...")
        ai = request_asteroids(radar, radius=args.radius, timeout=args.timeout)
        if not ai:
            print("ERROR: No asteroid index received (timeout).")
            return

        items = ai.get("items", [])
        if not items:
            print("No asteroids found in range.")
            return

        # Filter to asteroids only, sort by distance
        asteroids = [a for a in items if a.get("kind", "asteroid") == "asteroid"]
        asteroids.sort(key=lambda a: a.get("distance", float("inf")))

        # Load known ores
        owner_id = args.owner_id or resolve_owner_id()
        ores = load_known_ores(owner_id)
        print(f"Loaded {len(ores)} known ore deposits from SharedMap.")

        # Classify
        explored, unexplored = classify_asteroids(asteroids, ores)

        # Sort each group by distance
        explored.sort(key=lambda a: a.get("distance", float("inf")))
        unexplored.sort(key=lambda a: a.get("distance", float("inf")))

        # Report
        print()
        print_report(grid_name, grid_pos, explored, unexplored, args.gps)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
