#!/usr/bin/env python3
"""
Asteroid Scout — fly to nearby asteroids, scan for ores, find ice and resources.

Usage:
  python3 scripts/asteroid_scout.py --grid skynet-worker0 [--max-asteroids 5]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SECONTROL_PATH = os.path.join(os.path.dirname(__file__), '..', 'src')
if SECONTROL_PATH not in sys.path:
    sys.path.insert(0, SECONTROL_PATH)

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.controllers.space_navigator_controller import SpaceNavigatorController, SpeedZone
from secontrol.tools.navigation_tools import get_world_position

ORE_MAPS_DIR = Path(__file__).parent.parent / 'se-data' / 'ore-maps'


def get_asteroids(od, radius=50000, limit=50):
    """Request asteroid index from ore detector."""
    prev = (od.telemetry or {}).get('asteroidIndex')
    prev_rev = prev.get('revision') if isinstance(prev, dict) else None

    od.send_command({
        'cmd': 'asteroids',
        'targetId': int(od.device_id),
        'state': {
            'radius': float(radius),
            'limit': limit,
            'includePlanets': False,
        },
    })

    deadline = time.time() + 15
    while time.time() < deadline:
        od.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        ai = (od.telemetry or {}).get('asteroidIndex')
        if isinstance(ai, dict) and ai.get('ready') and ai.get('revision') != prev_rev:
            return ai.get('items', [])
    return []


def scan_ores(od, radius=800, cell_size=10):
    """Do an ore-only scan from current position."""
    ctrl = RadarController(
        od,
        radius=radius,
        cell_size=cell_size,
        boundingBoxX=80,
        boundingBoxY=80,
        ore_only=True,
    )
    result = ctrl.scan_voxels()
    # result is (solid, meta, contacts, ore_cells)
    if result and len(result) >= 4:
        return result[3] or []
    return []


def save_ore_map(asteroid_name, center, approx_radius, ship_pos, ores):
    """Save ore data to JSON file."""
    ORE_MAPS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = ORE_MAPS_DIR / f'{asteroid_name}.json'
    data = {
        'asteroid': asteroid_name,
        'center': center,
        'approx_radius': approx_radius,
        'scanned_from': list(ship_pos),
        'scan_time': datetime.now(timezone.utc).isoformat(),
        'ores': [],
    }
    for ore in ores:
        data['ores'].append({
            'type': ore.get('ore', '?'),
            'position': ore.get('position', [0, 0, 0]),
            'content': ore.get('content', 0),
        })
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    return filepath


def main():
    parser = argparse.ArgumentParser(description='Asteroid Scout — find resources')
    parser.add_argument('--grid', required=True, help='Grid name')
    parser.add_argument('--max-asteroids', type=int, default=5, help='Max asteroids to visit')
    parser.add_argument('--scan-radius', type=int, default=50000, help='Asteroid search radius')
    parser.add_argument('--dry-run', action='store_true', help='Skip actual flight')
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    od = grid.get_first_device(OreDetectorDevice)
    rc = grid.get_first_device(RemoteControlDevice)

    # Enable RC
    rc.enable()
    time.sleep(0.5)

    # Get current position
    pos = grid.metadata.get('pos')
    ship_pos = (pos[0], pos[1], pos[2])
    print(f'Start position: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})')

    # First: scan ores at current position
    print()
    print('=' * 60)
    print('  SCAN AT CURRENT POSITION')
    print('=' * 60)
    ores_here = scan_ores(od, radius=1500, cell_size=10)
    ore_types_here = {}
    for ore in ores_here:
        ot = ore.get('ore', '?')
        ore_types_here.setdefault(ot, []).append(ore)
    if ores_here:
        print(f'Found {len(ores_here)} deposits:')
        for ot, deposits in sorted(ore_types_here.items()):
            print(f'  {ot}: {len(deposits)} deposits')
    else:
        print('No ores at current position')

    # Get asteroid list
    print()
    print(f'Scanning for asteroids within {args.scan_radius}m...')
    asteroids = get_asteroids(od, radius=args.scan_radius)
    # Filter to actual asteroids
    asteroids = [a for a in asteroids if isinstance(a, dict) and a.get('kind') == 'asteroid']
    asteroids.sort(key=lambda a: a.get('surfaceDistance', 999999))
    print(f'Found {len(asteroids)} asteroids')

    # Load already-scanned
    scanned = set()
    if ORE_MAPS_DIR.exists():
        for f in ORE_MAPS_DIR.glob('*.json'):
            scanned.add(f.stem)

    # Visit unscanned asteroids
    visited = 0
    all_results = []
    ice_found = False

    for asteroid in asteroids[:args.max_asteroids * 2]:  # check more in case some are scanned
        if visited >= args.max_asteroids:
            break

        name = asteroid.get('name', 'unknown')
        center = asteroid.get('center', [0, 0, 0])
        dist = asteroid.get('distance', 0)
        surface = asteroid.get('surfaceDistance', 0)
        radius = asteroid.get('approxRadius', 0)

        if name in scanned:
            print(f'  [skip] {name} — already scanned')
            continue

        visited += 1
        print()
        print('=' * 60)
        print(f'  ASTEROID {visited}/{args.max_asteroids}: {name}')
        print(f'  Center: ({center[0]:.0f}, {center[1]:.0f}, {center[2]:.0f})')
        print(f'  Distance: {dist:.0f}m, Surface: {surface:.0f}m, Radius: {radius:.0f}m')
        print('=' * 60)

        # Calculate approach point — stop 200m from surface
        import math
        dx = center[0] - ship_pos[0]
        dy = center[1] - ship_pos[1]
        dz = center[2] - ship_pos[2]
        d = math.sqrt(dx*dx + dy*dy + dz*dz)
        if d > 0:
            approach_dist = max(radius + 200, 500)
            ratio = approach_dist / d
            target = (
                center[0] - dx * ratio / d * (d - approach_dist) / d if d > approach_dist else center[0],
                center[1] - dy * ratio / d * (d - approach_dist) / d if d > approach_dist else center[1],
                center[2] - dz * ratio / d * (d - approach_dist) / d if d > approach_dist else center[2],
            )
            # Simpler: fly to a point approach_dist from center along the line
            if d > approach_dist:
                frac = (d - approach_dist) / d
                target = (
                    ship_pos[0] + dx * (1 - frac),
                    ship_pos[1] + dy * (1 - frac),
                    ship_pos[2] + dz * (1 - frac),
                )
            else:
                # Already close, just scan from here
                target = ship_pos

        print(f'  Approach target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})')
        print(f'  Flight distance: {d - approach_dist:.0f}m' if d > approach_dist else '  Already close enough')

        if args.dry_run:
            print('  [DRY RUN] Skipping flight')
        elif d > 500:  # Only fly if > 500m away
            print(f'  Flying... ({d:.0f}m)')
            speed_zone = SpeedZone(max_speed=50, far_speed=30, medium_speed=15, close_speed=3)
            nav = SpaceNavigatorController(
                grid_name=args.grid,
                ship_radius=30,
                arrival_distance=200,
                speed_zone=speed_zone,
                dry_run=False,
            )
            try:
                result = nav.navigate_to(target)
                if result:
                    print(f'  Arrived at ({result[0]:.0f}, {result[1]:.0f}, {result[2]:.0f})')
                else:
                    print('  Navigation returned None, scanning from current position')
            except Exception as e:
                print(f'  Navigation error: {e}, scanning from current position')
            finally:
                nav.stop()
            time.sleep(2)

        # Scan for ores
        print('  Scanning for ores...')
        ores = scan_ores(od, radius=800, cell_size=10)
        print(f'  Found {len(ores)} ore deposit(s)')

        ore_types = {}
        has_ice = False
        for ore in ores:
            ot = ore.get('ore', '?')
            ore_types.setdefault(ot, []).append(ore)
            if 'ice' in ot.lower():
                has_ice = True

        for ot, deposits in sorted(ore_types.items()):
            print(f'    {ot}: {len(deposits)} deposits')

        # Save
        pos_now = grid.metadata.get('pos')
        filepath = save_ore_map(name, center, radius, pos_now, ores)
        print(f'  Saved to {filepath}')

        all_results.append({
            'name': name,
            'center': center,
            'distance': dist,
            'surface_distance': surface,
            'radius': radius,
            'ores': ore_types,
            'total_deposits': len(ores),
            'has_ice': has_ice,
        })

        if has_ice:
            print()
            print('🧊🧊🧊 ICE FOUND! 🧊🧊🧊')
            ice_found = True

        # Update ship position for next iteration
        ship_pos = (pos_now[0], pos_now[1], pos_now[2])

    # Summary
    print()
    print('=' * 60)
    print('  EXPLORATION SUMMARY')
    print('=' * 60)
    print(f'  Asteroids visited: {visited}')
    print(f'  Ice found: {"YES ✅" if ice_found else "NO ❌"}')
    print()
    for r in all_results:
        ice_mark = "🧊" if r['has_ice'] else "  "
        ores_str = ", ".join(f"{k}:{len(v)}" for k, v in r['ores'].items())
        print(f'  {ice_mark} {r["name"]}: {ores_str or "empty"} ({r["distance"]:.0f}m)')

    # Save summary
    summary_path = ORE_MAPS_DIR / 'scout_summary.json'
    with open(summary_path, 'w') as f:
        json.dump({
            'scan_time': datetime.now(timezone.utc).isoformat(),
            'asteroids_visited': visited,
            'ice_found': ice_found,
            'results': all_results,
        }, f, indent=2)
    print(f'\n  Summary saved to {summary_path}')

    close(grid)


if __name__ == '__main__':
    main()
