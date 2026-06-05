"""
Space Survey — обзор астероидов и руд вокруг корабля.

Основной скрипт для навигации в космосе. Отвечает на вопросы:
  - Какие астероиды вокруг меня?
  - На каких уже разведана руда? Какая?
  - Какие астероиды ещё не разведаны?
  - Где ближайший неисследованный астероид?
  - Где нужная мне руда (Platinum, Gold, Ice...)?

Usage:
    python examples/organized/radar/space_survey.py --grid agent1                         # обзор 20км
    python examples/organized/radar/space_survey.py --grid agent1 --radius 50000          # обзор 50км
    python examples/organized/radar/space_survey.py --grid agent1 --ore Platinum          # где платина?
    python examples/organized/radar/space_survey.py --grid agent1 --unexplored            # только неразведанные
    python examples/organized/radar/space_survey.py --grid agent1 --gps                   # GPS-маркеры
    python examples/organized/radar/space_survey.py --grid agent1 --json                  # JSON-вывод
"""

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from secontrol.common import close, prepare_grid, resolve_owner_id
from secontrol.controllers import SharedMapController
from secontrol.controllers.shared_map_controller import OreHit
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.tools.navigation_tools import get_world_position

DEFAULT_RADIUS = 50_000


def request_asteroids(
    radar: OreDetectorDevice,
    *,
    radius: float = DEFAULT_RADIUS,
    limit: int = 320,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Request fresh asteroid index from radar."""
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


def get_ship_position(grid) -> Optional[Tuple[float, float, float]]:
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
    """Load ore deposits from SharedMap (Redis), fallback to JSON files."""
    try:
        ctrl = SharedMapController(owner_id=owner_id, storage_backend="redis")
        ctrl.load()
        ores = ctrl.get_known_ores(material=material)
        if ores:
            return ores
    except Exception:
        pass

    # Fallback: JSON files
    json_paths = [
        Path.home() / "hermeswebui" / "se-data" / "scans" / "ore_latest.json",
        Path.home() / "hermeswebui" / "se-data" / "ore_database.jsonl",
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
    """Check if a point is within asteroid's approximate radius."""
    if not center or len(center) < 3:
        return False
    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(point, center[:3])))
    return d <= approx_radius * margin


def classify_asteroids(
    asteroids: List[Dict[str, Any]],
    ores: List[OreHit],
    ore_filter: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split asteroids into explored and unexplored.

    If ore_filter is set, only asteroids with that ore type are "explored".
    Returns (explored, unexplored).
    """
    explored = []
    unexplored = []

    for ast in asteroids:
        center = ast.get("center", [])
        radius = ast.get("approxRadius", 500)
        if not center or len(center) < 3:
            unexplored.append({**ast, "ore_types": {}, "ore_total": 0})
            continue

        ast_ores: Dict[str, int] = defaultdict(int)
        for ore in ores:
            if point_in_asteroid(ore.position, center, radius):
                ast_ores[ore.material] += 1

        entry = {
            **ast,
            "ore_types": dict(ast_ores),
            "ore_total": sum(ast_ores.values()),
        }

        if ore_filter:
            # Only count as explored if it has the filtered ore
            if any(ore_filter.lower() in k.lower() for k in ast_ores):
                explored.append(entry)
            else:
                unexplored.append(entry)
        elif ast_ores:
            explored.append(entry)
        else:
            unexplored.append(entry)

    explored.sort(key=lambda a: a.get("distance", float("inf")))
    unexplored.sort(key=lambda a: a.get("distance", float("inf")))
    return explored, unexplored


def gps_string(name: str, pos, color: str = "#FF8800") -> str:
    return f"GPS:{name}:{pos[0]}:{pos[1]}:{pos[2]}:{color}:"


def fmt_dist(meters) -> str:
    try:
        m = float(meters)
        if m >= 1000:
            return f"{m/1000:.1f}km"
        return f"{m:.0f}m"
    except (TypeError, ValueError):
        return "?"


def print_table_report(
    grid_name: str,
    ship_pos: Optional[Tuple[float, float, float]],
    explored: List[Dict[str, Any]],
    unexplored: List[Dict[str, Any]],
    ore_filter: Optional[str],
    show_gps: bool,
    max_rows: int = 0,
) -> None:
    """Print human-readable table report."""
    total = len(explored) + len(unexplored)

    # Header
    print(f"Grid: {grid_name}")
    if ship_pos:
        print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
    filter_str = f"  filter: {ore_filter}" if ore_filter else ""
    print(f"Range: {total} asteroids  |  Explored: {len(explored)}  |  Unexplored: {len(unexplored)}{filter_str}")

    # Explored asteroids with ores
    if explored:
        print(f"\n{'='*90}")
        print(f"  EXPLORED ({len(explored)}) — known ores")
        print(f"{'='*90}")
        print(f"  {'#':>3}  {'Dist':>7}  {'Surf':>7}  {'Rad':>5}  {'Ores':>5}  {'Types':35}  Name")
        print(f"  {'-'*86}")

        display = explored[:max_rows] if max_rows > 0 else explored
        for i, ast in enumerate(display):
            name = ast.get("name", "?")
            dist = ast.get("distance", 0)
            surf = ast.get("surfaceDistance", 0)
            radius = ast.get("approxRadius", 0)
            ore_types = ast.get("ore_types", {})
            ore_total = ast.get("ore_total", 0)

            types_str = ", ".join(f"{k}:{v}" for k, v in sorted(ore_types.items(), key=lambda x: -x[1]))
            if len(types_str) > 35:
                types_str = types_str[:32] + "..."

            print(f"  {i+1:>3}  {fmt_dist(dist):>7}  {fmt_dist(surf):>7}  {fmt_dist(radius):>5}  {ore_total:>5}  {types_str:35}  {name}")

            if show_gps:
                center = ast.get("center", [])
                if len(center) >= 3:
                    print(f"       {gps_string(name, center, '#00FF88')}")

        if max_rows > 0 and len(explored) > max_rows:
            print(f"  ... and {len(explored) - max_rows} more")

    # Unexplored asteroids
    if unexplored:
        print(f"\n{'='*90}")
        print(f"  UNEXPLORED ({len(unexplored)}) — no ore data")
        print(f"{'='*90}")
        print(f"  {'#':>3}  {'Dist':>7}  {'Surf':>7}  {'Rad':>5}  {'GPS':50}  Name")
        print(f"  {'-'*86}")

        display = unexplored[:max_rows] if max_rows > 0 else unexplored
        for i, ast in enumerate(display):
            name = ast.get("name", "?")
            dist = ast.get("distance", 0)
            surf = ast.get("surfaceDistance", 0)
            radius = ast.get("approxRadius", 0)
            center = ast.get("center", [])

            gps = ""
            if show_gps and len(center) >= 3:
                gps = gps_string(name, center, "#FF8800")

            print(f"  {i+1:>3}  {fmt_dist(dist):>7}  {fmt_dist(surf):>7}  {fmt_dist(radius):>5}  {gps:50}  {name}")

        if max_rows > 0 and len(unexplored) > max_rows:
            print(f"  ... and {len(unexplored) - max_rows} more")

    # Recommendation
    print(f"\n{'='*90}")
    if unexplored:
        best = unexplored[0]
        name = best.get("name", "?")
        dist = fmt_dist(best.get("distance"))
        center = best.get("center", [])
        print(f"  NEXT: fly to {name} ({dist} away) — unexplored")
        if len(center) >= 3:
            print(f"  Center: ({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})")
            print(f"  {gps_string(name, center, '#FFFF00')}")
    elif explored:
        if ore_filter:
            print(f"  All asteroids with '{ore_filter}' are already explored!")
        else:
            print(f"  All visible asteroids are explored!")
    else:
        print(f"  No asteroids found. Try --radius 50000")


def print_json_report(
    grid_name: str,
    ship_pos: Optional[Tuple[float, float, float]],
    explored: List[Dict[str, Any]],
    unexplored: List[Dict[str, Any]],
    ore_filter: Optional[str],
) -> None:
    """Print JSON output for programmatic use."""
    def clean_ast(ast):
        return {
            "name": ast.get("name"),
            "distance": ast.get("distance"),
            "surfaceDistance": ast.get("surfaceDistance"),
            "approxRadius": ast.get("approxRadius"),
            "center": ast.get("center"),
            "ore_types": ast.get("ore_types", {}),
            "ore_total": ast.get("ore_total", 0),
            "gps": gps_string(ast.get("name", ""), ast.get("center", [])) if ast.get("center") else None,
        }

    result = {
        "grid": grid_name,
        "ship_position": list(ship_pos) if ship_pos else None,
        "ore_filter": ore_filter,
        "summary": {
            "total": len(explored) + len(unexplored),
            "explored": len(explored),
            "unexplored": len(unexplored),
        },
        "explored": [clean_ast(a) for a in explored],
        "unexplored": [clean_ast(a) for a in unexplored],
    }

    if unexplored:
        best = unexplored[0]
        result["recommendation"] = {
            "action": "fly_to_unexplored",
            "name": best.get("name"),
            "distance": best.get("distance"),
            "center": best.get("center"),
        }

    print(json.dumps(result, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(
        description="Space Survey — обзор астероидов и руд вокруг корабля",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/organized/radar/space_survey.py --grid agent1                    # обзор 20км
  python examples/organized/radar/space_survey.py --grid agent1 --radius 50000    # обзор 50км
  python examples/organized/radar/space_survey.py --grid agent1 --ore Platinum    # где платина?
  python examples/organized/radar/space_survey.py --grid agent1 --unexplored      # только неразведанные
  python examples/organized/radar/space_survey.py --grid agent1 --gps             # GPS-маркеры
  python examples/organized/radar/space_survey.py --grid agent1 --json            # JSON
  python examples/organized/radar/space_survey.py --grid agent1 --max 20          # максимум строк
""",
    )
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name or ID")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS, help="Search radius in meters (default: 20000)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Asteroid index timeout (s)")
    parser.add_argument("--ore", default=None, metavar="TYPE", help="Filter: show only asteroids with this ore (Platinum, Gold, Ice...)")
    parser.add_argument("--unexplored", action="store_true", help="Show only unexplored asteroids")
    parser.add_argument("--gps", action="store_true", help="Show GPS markers for SE")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--max", type=int, default=20, help="Max rows per section (0=all)")
    parser.add_argument("--owner-id", default=None, help="Owner ID for SharedMap")
    args = parser.parse_args()

    # Connect
    grid = prepare_grid(args.grid)
    grid_name = grid.name

    try:
        ship_pos = get_ship_position(grid)

        # Request asteroid index
        radar = grid.get_first_device(OreDetectorDevice)
        if not radar:
            print("ERROR: No Ore Detector found on grid!")
            return

        if not args.json:
            print(f"Scanning asteroids (radius={fmt_dist(args.radius)})...")

        ai = request_asteroids(radar, radius=args.radius, timeout=args.timeout)
        if not ai:
            print("ERROR: No asteroid index received (timeout).")
            return

        items = ai.get("items", [])
        asteroids = [a for a in items if a.get("kind", "asteroid") == "asteroid"]
        asteroids.sort(key=lambda a: a.get("distance", float("inf")))

        if not asteroids:
            print("No asteroids found in range.")
            return

        # Load known ores
        owner_id = args.owner_id or resolve_owner_id()
        ores = load_known_ores(owner_id, material=args.ore)

        # Classify
        explored, unexplored = classify_asteroids(asteroids, ores, ore_filter=args.ore)

        # If --unexplored, clear explored list
        if args.unexplored and not args.ore:
            explored_for_display = []
        else:
            explored_for_display = explored

        # Output
        if args.json:
            print_json_report(grid_name, ship_pos, explored_for_display, unexplored, args.ore)
        else:
            print_table_report(
                grid_name, ship_pos,
                explored_for_display if not args.unexplored else [],
                unexplored,
                args.ore,
                args.gps,
                max_rows=args.max if args.max > 0 else 0,
            )

    finally:
        close(grid)


if __name__ == "__main__":
    main()
