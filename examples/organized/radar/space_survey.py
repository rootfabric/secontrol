"""
Space Survey — обзор астероидов и руд вокруг корабля.

Показывает астероиды вокруг грида, известные залежи руды из SharedMap/JSON
и ближайшие точки руды даже если asteroidIndex вернул не весь список астероидов.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from secontrol.common import close, prepare_grid, resolve_owner_id
from secontrol.controllers import SharedMapController
from secontrol.controllers.shared_map_controller import OreHit
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.tools.navigation_tools import get_world_position

DEFAULT_RADIUS = 100_000.0
DEFAULT_LIMIT = 5000
DEFAULT_MATCH_MARGIN = 1.5
SCANS_DIR = Path.home() / "hermeswebui" / "se-data" / "scans"
ORE_DB_PATH = Path.home() / "hermeswebui" / "se-data" / "ore_database.jsonl"


class OreLoadResult:
    def __init__(self, ores: List[OreHit], sources: Dict[str, int], errors: List[str]) -> None:
        self.ores = ores
        self.sources = sources
        self.errors = errors


def dist3(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def material_matches(material: str, wanted: Optional[str]) -> bool:
    if not wanted:
        return True
    return wanted.lower() in material.lower()


def request_asteroids(
    radar: OreDetectorDevice,
    *,
    radius: float = DEFAULT_RADIUS,
    limit: int = DEFAULT_LIMIT,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Request fresh asteroid index from radar."""
    radar.update()
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_rev = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command(
        {
            "cmd": "asteroids",
            "targetId": int(radar.device_id),
            "state": {
                "radius": float(radius),
                "limit": int(limit),
                "includePlanets": False,
            },
        }
    )

    deadline = time.time() + timeout
    latest_ready: Optional[Dict[str, Any]] = None
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        ai = telemetry.get("asteroidIndex")
        if not isinstance(ai, dict) or not ai.get("ready"):
            continue
        latest_ready = ai
        rev = ai.get("revision")
        if rev != previous_rev:
            return ai

    return latest_ready


def get_ship_position(grid: Any) -> Optional[Tuple[float, float, float]]:
    """Get grid world position from cockpit or remote control."""
    for dev_type in ("cockpit", "remote_control"):
        devices = grid.find_devices_by_type(dev_type)
        if not devices:
            continue
        devices[0].update()
        pos = get_world_position(devices[0])
        if pos:
            return (float(pos[0]), float(pos[1]), float(pos[2]))
    return None


def gps_string(name: str, pos: Iterable[float], color: str = "#FF8800") -> str:
    p = list(pos)
    return f"GPS:{name}:{p[0]}:{p[1]}:{p[2]}:{color}:"


def fmt_dist(meters: Any) -> str:
    try:
        m = float(meters)
        if m >= 1000:
            return f"{m / 1000:.1f}km"
        return f"{m:.0f}m"
    except (TypeError, ValueError):
        return "?"


def normalize_ore_hit(material: str, position: Any, content: Any = None) -> Optional[OreHit]:
    if not position or len(position) != 3:
        return None
    try:
        pos = (float(position[0]), float(position[1]), float(position[2]))
    except (TypeError, ValueError):
        return None
    return OreHit(material=str(material or "unknown"), position=pos, content=content)


def load_json_ores(material: Optional[str]) -> OreLoadResult:
    results: List[OreHit] = []
    sources: Dict[str, int] = {}
    errors: List[str] = []
    json_paths = [SCANS_DIR / "ore_latest.json", ORE_DB_PATH]

    for path in json_paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue

        before = len(results)
        if path.suffix == ".jsonl":
            lines = text.splitlines()
            entries: List[Dict[str, Any]] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    entries.append(data)
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}: {exc}")
                continue
            entries = [data] if isinstance(data, dict) else []

        for entry in entries:
            for dep in entry.get("all_deposits", []):
                ore_name = str(dep.get("ore_type") or dep.get("material") or dep.get("ore") or "")
                if not material_matches(ore_name, material):
                    continue
                hit = normalize_ore_hit(ore_name, dep.get("position"), dep.get("content"))
                if hit:
                    results.append(hit)

        added = len(results) - before
        if added:
            sources[str(path)] = added

    return OreLoadResult(results, sources, errors)


def load_known_ores(owner_id: str, material: Optional[str] = None, debug: bool = False) -> OreLoadResult:
    """Load ore deposits from Redis and JSON, merging both sources instead of fallback-only."""
    ore_map: Dict[Tuple[str, Tuple[float, float, float]], OreHit] = {}
    sources: Dict[str, int] = {}
    errors: List[str] = []

    try:
        ctrl = SharedMapController(owner_id=owner_id, storage_backend="redis")
        all_ores = ctrl.get_known_ores(material=None)
        matched = [ore for ore in all_ores if material_matches(ore.material, material)]
        for ore in matched:
            ore_map[(ore.material, ore.position)] = ore
        sources[f"redis:{ctrl.memory_prefix}"] = len(matched)
    except Exception as exc:
        errors.append(f"Redis SharedMap failed: {exc}")

    json_result = load_json_ores(material)
    for ore in json_result.ores:
        ore_map[(ore.material, ore.position)] = ore
    sources.update(json_result.sources)
    errors.extend(json_result.errors)

    ores = list(ore_map.values())
    if debug:
        print("\nDEBUG ore sources:")
        for source, count in sources.items():
            print(f"  {source}: {count}")
        if errors:
            print("DEBUG ore load errors:")
            for err in errors:
                print(f"  {err}")
        print(f"DEBUG known ores matched: {len(ores)}")

    return OreLoadResult(ores, sources, errors)


def point_in_asteroid(
    point: Tuple[float, float, float],
    center: List[float],
    approx_radius: float,
    margin: float = DEFAULT_MATCH_MARGIN,
) -> bool:
    if not center or len(center) < 3:
        return False
    asteroid_center = (float(center[0]), float(center[1]), float(center[2]))
    return dist3(point, asteroid_center) <= float(approx_radius) * float(margin)


def classify_asteroids(
    asteroids: List[Dict[str, Any]],
    ores: List[OreHit],
    ore_filter: Optional[str] = None,
    match_margin: float = DEFAULT_MATCH_MARGIN,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[OreHit]]:
    explored: List[Dict[str, Any]] = []
    unexplored: List[Dict[str, Any]] = []
    matched_ore_keys: set[Tuple[str, Tuple[float, float, float]]] = set()

    for ast in asteroids:
        center = ast.get("center", [])
        radius = float(ast.get("approxRadius", 500) or 500)
        if not center or len(center) < 3:
            unexplored.append({**ast, "ore_types": {}, "ore_total": 0})
            continue

        ast_ores: Dict[str, int] = defaultdict(int)
        for ore in ores:
            if point_in_asteroid(ore.position, center, radius, margin=match_margin):
                ast_ores[ore.material] += 1
                matched_ore_keys.add((ore.material, ore.position))

        entry = {**ast, "ore_types": dict(ast_ores), "ore_total": sum(ast_ores.values())}
        if ore_filter:
            if any(material_matches(material, ore_filter) for material in ast_ores):
                explored.append(entry)
            else:
                unexplored.append(entry)
        elif ast_ores:
            explored.append(entry)
        else:
            unexplored.append(entry)

    unmatched = [ore for ore in ores if (ore.material, ore.position) not in matched_ore_keys]
    explored.sort(key=lambda a: a.get("distance", float("inf")))
    unexplored.sort(key=lambda a: a.get("distance", float("inf")))
    return explored, unexplored, unmatched


def nearest_ore_hits(
    ores: List[OreHit],
    ship_pos: Optional[Tuple[float, float, float]],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for ore in ores:
        distance = dist3(ship_pos, ore.position) if ship_pos else None
        hits.append(
            {
                "material": ore.material,
                "position": ore.position,
                "content": ore.content,
                "distance": distance,
                "gps": gps_string(ore.material, ore.position, "#FF00FF"),
            }
        )
    hits.sort(key=lambda item: item["distance"] if item["distance"] is not None else float("inf"))
    return hits[:limit]


def print_direct_ore_hits(title: str, hits: List[Dict[str, Any]], show_gps: bool) -> None:
    if not hits:
        return
    print(f"\n{'=' * 90}")
    print(f"  {title}")
    print(f"{'=' * 90}")
    print(f"  {'#':>3}  {'Dist':>7}  {'Ore':18}  {'Content':>8}  Position")
    print(f"  {'-' * 86}")
    for i, hit in enumerate(hits, start=1):
        pos = hit["position"]
        print(
            f"  {i:>3}  {fmt_dist(hit['distance']):>7}  "
            f"{hit['material'][:18]:18}  {str(hit.get('content')):>8}  "
            f"({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})"
        )
        if show_gps:
            print(f"       {hit['gps']}")


def print_table_report(
    grid_name: str,
    ship_pos: Optional[Tuple[float, float, float]],
    explored: List[Dict[str, Any]],
    unexplored: List[Dict[str, Any]],
    ore_filter: Optional[str],
    show_gps: bool,
    max_rows: int = 0,
    returned_count: int = 0,
    requested_limit: int = DEFAULT_LIMIT,
) -> None:
    total = len(explored) + len(unexplored)
    print(f"Grid: {grid_name}")
    if ship_pos:
        print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
    filter_str = f"  filter: {ore_filter}" if ore_filter else ""
    cap_note = ""
    if returned_count >= requested_limit:
        cap_note = f"  WARNING: asteroid list reached limit={requested_limit}; farther asteroids may be hidden"
    print(
        f"Returned: {returned_count} asteroids  |  Classified: {total}  |  "
        f"Explored: {len(explored)}  |  Unexplored: {len(unexplored)}{filter_str}{cap_note}"
    )

    if explored:
        print(f"\n{'=' * 90}")
        print(f"  EXPLORED ({len(explored)}) — known ores")
        print(f"{'=' * 90}")
        print(f"  {'#':>3}  {'Dist':>7}  {'Surf':>7}  {'Rad':>5}  {'Ores':>5}  {'Types':35}  Name")
        print(f"  {'-' * 86}")
        display = explored[:max_rows] if max_rows > 0 else explored
        for i, ast in enumerate(display, start=1):
            ore_types = ast.get("ore_types", {})
            types_str = ", ".join(f"{k}:{v}" for k, v in sorted(ore_types.items(), key=lambda x: -x[1]))
            if len(types_str) > 35:
                types_str = types_str[:32] + "..."
            print(
                f"  {i:>3}  {fmt_dist(ast.get('distance')):>7}  "
                f"{fmt_dist(ast.get('surfaceDistance')):>7}  {fmt_dist(ast.get('approxRadius')):>5}  "
                f"{ast.get('ore_total', 0):>5}  {types_str:35}  {ast.get('name', '?')}"
            )
            center = ast.get("center", [])
            if show_gps and len(center) >= 3:
                print(f"       {gps_string(ast.get('name', '?'), center, '#00FF88')}")
        if max_rows > 0 and len(explored) > max_rows:
            print(f"  ... and {len(explored) - max_rows} more")

    if unexplored:
        print(f"\n{'=' * 90}")
        print(f"  UNEXPLORED ({len(unexplored)}) — no ore data")
        print(f"{'=' * 90}")
        print(f"  {'#':>3}  {'Dist':>7}  {'Surf':>7}  {'Rad':>5}  {'GPS':50}  Name")
        print(f"  {'-' * 86}")
        display = unexplored[:max_rows] if max_rows > 0 else unexplored
        for i, ast in enumerate(display, start=1):
            center = ast.get("center", [])
            gps = gps_string(ast.get("name", "?"), center, "#FF8800") if show_gps and len(center) >= 3 else ""
            print(
                f"  {i:>3}  {fmt_dist(ast.get('distance')):>7}  "
                f"{fmt_dist(ast.get('surfaceDistance')):>7}  {fmt_dist(ast.get('approxRadius')):>5}  "
                f"{gps:50}  {ast.get('name', '?')}"
            )
        if max_rows > 0 and len(unexplored) > max_rows:
            print(f"  ... and {len(unexplored) - max_rows} more")

    print(f"\n{'=' * 90}")
    if ore_filter and explored:
        best = explored[0]
        center = best.get("center", [])
        print(f"  NEXT: fly to {best.get('name', '?')} ({fmt_dist(best.get('distance'))} away) — known {ore_filter}")
        if len(center) >= 3:
            print(f"  Center: ({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})")
            print(f"  {gps_string(best.get('name', '?'), center, '#00FF88')}")
    elif unexplored:
        best = unexplored[0]
        center = best.get("center", [])
        print(f"  NEXT: fly to {best.get('name', '?')} ({fmt_dist(best.get('distance'))} away) — unexplored")
        if len(center) >= 3:
            print(f"  Center: ({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})")
            print(f"  {gps_string(best.get('name', '?'), center, '#FFFF00')}")
    elif explored:
        print("  All visible asteroids are explored!")
    else:
        print("  No asteroids found. Try --radius 100000 --limit 5000")


def print_json_report(
    grid_name: str,
    ship_pos: Optional[Tuple[float, float, float]],
    explored: List[Dict[str, Any]],
    unexplored: List[Dict[str, Any]],
    direct_hits: List[Dict[str, Any]],
    ore_filter: Optional[str],
    returned_count: int,
    requested_limit: int,
) -> None:
    def clean_ast(ast: Dict[str, Any]) -> Dict[str, Any]:
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
            "returned_asteroids": returned_count,
            "requested_limit": requested_limit,
            "limit_reached": returned_count >= requested_limit,
            "explored": len(explored),
            "unexplored": len(unexplored),
            "direct_ore_hits": len(direct_hits),
        },
        "explored": [clean_ast(a) for a in explored],
        "unexplored": [clean_ast(a) for a in unexplored],
        "direct_ore_hits": direct_hits,
    }

    if ore_filter and explored:
        best = explored[0]
        result["recommendation"] = {"action": "fly_to_known_ore", "name": best.get("name"), "center": best.get("center")}
    elif direct_hits:
        result["recommendation"] = {"action": "fly_to_direct_ore_hit", **direct_hits[0]}
    elif unexplored:
        best = unexplored[0]
        result["recommendation"] = {"action": "fly_to_unexplored", "name": best.get("name"), "center": best.get("center")}

    print(json.dumps(result, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Space Survey — обзор астероидов и руд вокруг корабля",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name or ID")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS, help="Search radius in meters")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max asteroid index items")
    parser.add_argument("--timeout", type=float, default=10.0, help="Asteroid index timeout in seconds")
    parser.add_argument("--ore", default=None, metavar="TYPE", help="Filter: show only asteroids with this ore")
    parser.add_argument("--unexplored", action="store_true", help="Show only unexplored asteroids")
    parser.add_argument("--gps", action="store_true", help="Show GPS markers for SE")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--max", type=int, default=20, help="Max rows per section, 0 means all")
    parser.add_argument("--owner-id", default=None, help="Owner ID for SharedMap")
    parser.add_argument("--match-margin", type=float, default=DEFAULT_MATCH_MARGIN, help="Asteroid radius multiplier for ore matching")
    parser.add_argument("--debug", action="store_true", help="Print asteroid and ore loading diagnostics")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    grid_name = grid.name

    try:
        ship_pos = get_ship_position(grid)
        radar = grid.get_first_device(OreDetectorDevice)
        if not radar:
            print("ERROR: No Ore Detector found on grid!")
            return

        if not args.json:
            print(f"Scanning asteroids (radius={fmt_dist(args.radius)}, limit={args.limit})...")

        ai = request_asteroids(radar, radius=args.radius, limit=args.limit, timeout=args.timeout)
        if not ai:
            print("ERROR: No asteroid index received (timeout).")
            return

        items = ai.get("items", [])
        asteroids = [a for a in items if isinstance(a, dict) and a.get("kind", "asteroid") == "asteroid"]
        asteroids.sort(key=lambda a: a.get("distance", float("inf")))

        if args.debug and not args.json:
            print("\nDEBUG asteroidIndex:")
            print(f"  revision: {ai.get('revision')}")
            print(f"  requested radius: {args.radius}")
            print(f"  requested limit: {args.limit}")
            print(f"  raw items: {len(items)}")
            print(f"  asteroid items: {len(asteroids)}")
            print(f"  keys: {sorted(ai.keys())}")

        if not asteroids:
            print("No asteroids found in range.")
            return

        owner_id = args.owner_id or resolve_owner_id()
        ore_result = load_known_ores(owner_id, material=args.ore, debug=args.debug and not args.json)
        ores = ore_result.ores

        explored, unexplored, unmatched_ores = classify_asteroids(
            asteroids,
            ores,
            ore_filter=args.ore,
            match_margin=args.match_margin,
        )
        explored_for_display = [] if args.unexplored and not args.ore else explored
        direct_hits = nearest_ore_hits(unmatched_ores, ship_pos, limit=args.max if args.max > 0 else 20)

        if args.json:
            print_json_report(
                grid_name,
                ship_pos,
                explored_for_display,
                unexplored,
                direct_hits,
                args.ore,
                len(asteroids),
                args.limit,
            )
        else:
            print_table_report(
                grid_name,
                ship_pos,
                explored_for_display if not args.unexplored else [],
                unexplored,
                args.ore,
                args.gps,
                max_rows=args.max if args.max > 0 else 0,
                returned_count=len(asteroids),
                requested_limit=args.limit,
            )
            if args.ore and direct_hits:
                print_direct_ore_hits("DIRECT ORE HITS — known ore not attached to returned asteroidIndex", direct_hits, args.gps)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
