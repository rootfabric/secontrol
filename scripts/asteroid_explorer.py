#!/usr/bin/env python3
"""
Asteroid Explorer — fly to unexplored asteroids, scan for ores, find ice.

Usage:
  python3 scripts/asteroid_explorer.py --grid skynet-baza0 [--max-asteroids 10] [--scan-radius 2000]
"""

import argparse
import json
import math
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
from secontrol.controllers.space_navigator_controller import SpaceNavigatorController
from secontrol.tools.navigation_tools import get_world_position

ORE_MAPS_DIR = Path(__file__).parent.parent / 'se-data' / 'ore-maps'


def get_asteroids(radar, radius=20000, limit=50):
    """Request asteroid index from the ore detector."""
    telemetry = radar.telemetry or {}
    prev = telemetry.get('asteroidIndex')
    prev_rev = prev.get('revision') if isinstance(prev, dict) else None

    radar.send_command({
        'cmd': 'asteroids',
        'targetId': int(radar.device_id),
        'state': {
            'radius': float(radius),
            'limit': limit,
            'includePlanets': False,
        },
    })

    deadline = time.time() + 15
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        ai = telemetry.get('asteroidIndex')
        if isinstance(ai, dict) and ai.get('ready') and ai.get('revision') != prev_rev:
            return ai.get('items', [])
    return []


def scan_ores_at_asteroid(radar, radius=500, cell_size=10):
    """Do an ore-only scan and return list of ore deposits."""
    ctrl = RadarController(
        radar,
        radius=radius,
        cell_size=cell_size,
        boundingBoxX=80,
        boundingBoxY=80,
        ore_only=True,
    )
    solid, meta, contacts, ore_cells = ctrl.scan_voxels()
    return ore_cells or []


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
    parser = argparse.ArgumentParser(description='Asteroid Explorer — find ice')
    parser.add_argument('--grid', required=True, help='Grid name')
    parser.add_argument('--max-asteroids', type=int, default=10, help='Max asteroids to visit')
    parser.add_argument('--scan-radius', type=int, default=20000, help='Asteroid search radius')
    parser.add_argument('--arrival', type=float, default=300, help='Arrival distance from center')
    parser.add_argument('--max-speed', type=float, default=50, help='Max flight speed')
    parser.add_argument('--dry-run', action='store_true', help='Skip actual flight')
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    radar = grid.get_first_device(OreDetectorDevice)
    rc = grid.get_first_device(RemoteControlDevice)

    # Get current position
    rc.update()
    ship_pos = get_world_position(rc)
    print(f'Start position: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})')

    # Get asteroid list
    print(f'Scanning for asteroids within {args.scan_radius}m...')
    asteroids = get_asteroids(radar, radius=args.scan_radius, limit=50)
    print(f'Found {len(asteroids)} asteroids')

    # Load already-scanned asteroids
    scanned = set()
    if ORE_MAPS_DIR.exists():
        for f in ORE_MAPS_DIR.glob('*.json'):
            scanned.add(f.stem)

    # Filter out already-scanned and sort by distance
    unscanned = []
    for a in asteroids:
        name = a.get('name', '')
        if name in scanned:
            print(f'  [skip] {name} — already scanned')
            continue
        unscanned.append(a)

    unscanned.sort(key=lambda a: a.get('distance', 999999))
    print(f'Unscanned asteroids: {len(unscanned)}')

    # Visit each unscanned asteroid
    ice_found = False
    visited = 0

    for asteroid in unscanned[:args.max_asteroids]:
        name = asteroid.get('name', 'unknown')
        center = asteroid.get('center', [0, 0, 0])
        dist = asteroid.get('distance', 0)
        surface = asteroid.get('surfaceDistance', 0)
        radius = asteroid.get('approxRadius', 0)

        print()
        print('=' * 60)
        print(f'  ASTEROID: {name}')
        print(f'  Center: ({center[0]:.0f}, {center[1]:.0f}, {center[2]:.0f})')
        print(f'  Distance: {dist:.0f}m, Surface: {surface:.0f}m, Radius: {radius:.0f}m')
        print('=' * 60)

        # Fly to asteroid
        target = (float(center[0]), float(center[1]), float(center[2]))
        print(f'Flying to asteroid center ({dist:.0f}m)...')

        if args.dry_run:
            print('[DRY RUN] Skipping flight')
        else:
            from secontrol.controllers.space_navigator_controller import SpeedZone
            speed_zone = SpeedZone(max_speed=args.max_speed)
            nav = SpaceNavigatorController(
                grid_name=args.grid,
                ship_radius=30,
                arrival_distance=args.arrival,
                speed_zone=speed_zone,
                dry_run=False,
            )
            try:
                result = nav.navigate_to(target)
            finally:
                nav.stop()

            if result:
                print(f'Arrived at ({result[0]:.0f}, {result[1]:.0f}, {result[2]:.0f})')
            else:
                print('Navigation failed, scanning from current position anyway')

            # Wait for ship to stabilize
            time.sleep(2)

        # Get current position for scan reference
        rc.update()
        scan_pos = get_world_position(rc)

        # Scan for ores
        print('Scanning for ores (ore_only=True)...')
        ores = scan_ores_at_asteroid(radar, radius=500, cell_size=10)
        print(f'Found {len(ores)} ore deposit(s)')

        # Show results
        has_ice = False
        ore_types = {}
        for ore in ores:
            ore_type = ore.get('ore', '?')
            if ore_type not in ore_types:
                ore_types[ore_type] = []
            ore_types[ore_type].append(ore)
            if 'ice' in ore_type.lower() or 'Ice' in ore_type:
                has_ice = True

        for ore_type, deposits in sorted(ore_types.items()):
            print(f'  {ore_type}: {len(deposits)} deposit(s)')
            for d in deposits:
                p = d.get('position', [0, 0, 0])
                print(f'    ({p[0]:.0f}, {p[1]:.0f}, {p[2]:.0f}) content={d.get("content", "?")}')

        # Save ore map
        filepath = save_ore_map(name, center, radius, scan_pos, ores)
        print(f'Saved to {filepath}')

        visited += 1

        if has_ice:
            print()
            print('🧊🧊🧊 ICE FOUND! 🧊🧊🧊')
            ice_found = True
            break

    print()
    print('=' * 60)
    print(f'  EXPLORATION COMPLETE')
    print(f'  Visited: {visited} asteroids')
    print(f'  Ice found: {"YES ✅" if ice_found else "NO ❌"}')
    print('=' * 60)

    close(grid)


if __name__ == '__main__':
    main()
