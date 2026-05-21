#!/usr/bin/env python3
"""
Автономная добыча льда для skynet-baza0.

Использует ore_detector для поиска астероидов и руды.
Приоритет: Ice > всё остальное.

Алгоритм:
1. Сканировать на астероиды (solid points) в радиусе 5000м
2. Если астероиды найдены → лететь к ближайшему, сканировать руду
3. Если нет → использовать координаты из прошлых сканов
4. Если и там нет → лететь в направлении и сканировать каждые 500м
5. Найден лёд → добывать до заполнения контейнера
6. Контейнер полон → вернуться на базу и пристыковаться
"""

import sys
import os
import time
import math
import json
from datetime import datetime

# Setup paths
env_path = '/workspace/.env'
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

sys.path.insert(0, '/workspace/src')

from secontrol.common import prepare_grid, close
from secontrol.redis_client import RedisEventClient
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import goto, get_world_position

# Constants
SHIP_ID = '90797522825535709'
BASE_ID = '133900526852669590'
OWNER = '144115188075855919'

SCAN_RADIUS = 5000
ORE_SCAN_RADIUS = 1000
MINE_DISTANCE = 50
CONTAINER_FULL_THRESHOLD = 0.9
SEARCH_STEP = 500  # шаг поиска в метрах
MAX_SEARCH_STEPS = 10  # максимум шагов поиска

# Known asteroid locations from previous scans
KNOWN_ASTEROID_SCANS = '/home/hermeswebui/se-data/scans/ore_latest.json'

client = RedisEventClient()
r = client.client

def _key(suffix):
    return f'se:{OWNER}:mining:{suffix}'

def get_visited():
    """Get list of visited asteroid positions."""
    data = r.get(_key('visited'))
    if data:
        return json.loads(data)
    return []

def add_visited(pos):
    """Mark an asteroid position as visited."""
    visited = get_visited()
    # Round to 100m grid to avoid near-duplicates
    rounded = (round(pos[0]/100)*100, round(pos[1]/100)*100, round(pos[2]/100)*100)
    if rounded not in visited:
        visited.append(rounded)
        r.set(_key('visited'), json.dumps(visited), ex=7200)

def clear_visited():
    """Clear visited list (new cycle)."""
    r.delete(_key('visited'))

def is_visited(pos, tolerance=200):
    """Check if position is near a visited asteroid."""
    visited = get_visited()
    for v in visited:
        if distance(pos, v) < tolerance:
            return True
    return False

def get_state():
    state = r.get(_key('state'))
    return state.decode() if state else 'idle'

def set_state(state):
    r.set(_key('state'), state, ex=7200)

def get_target():
    target = r.get(_key('target'))
    if target:
        data = json.loads(target)
        return (data['x'], data['y'], data['z'])
    return None

def set_target(x, y, z):
    r.set(_key('target'), json.dumps({'x': x, 'y': y, 'z': z}), ex=7200)

def get_grid():
    grid = prepare_grid(SHIP_ID)
    time.sleep(0.5)
    return grid

def get_position(grid):
    pos = grid.metadata.get('pos')
    return (pos[0], pos[1], pos[2])

def distance(a, b):
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))

def load_known_asteroids():
    """Load asteroid positions from previous scans."""
    if not os.path.exists(KNOWN_ASTEROID_SCANS):
        return []
    
    with open(KNOWN_ASTEROID_SCANS) as f:
        data = json.load(f)
    
    clusters = data.get('clusters', [])
    asteroids = []
    for cl in clusters:
        center = cl.get('center', [])
        if center:
            asteroids.append({
                'center': tuple(center),
                'ore_type': cl.get('ore_type', 'Unknown'),
                'deposits': cl.get('deposit_count', 0)
            })
    
    return asteroids

def scan_for_asteroids(grid):
    """Scan for asteroids (solid points) in range."""
    od = grid.get_first_device(OreDetectorDevice)
    if not od:
        return []
    
    od.enable()
    time.sleep(0.5)
    
    # Scan for voxels
    radar = RadarController(od, ore_only=False, radius=SCAN_RADIUS, cell_size=20, fullSolidScan=True)
    solid, meta, contacts, ore_cells = radar.scan_voxels()
    
    if not solid:
        return []
    
    # Cluster solid points to find asteroid centers
    asteroids = cluster_solid_points(solid)
    return asteroids

def cluster_solid_points(points, cluster_radius=100):
    """Cluster solid points to find asteroid centers."""
    if not points:
        return []
    
    remaining = list(points)
    clusters = []
    
    while remaining:
        seed = remaining.pop(0)
        cluster_pts = [seed]
        new_remaining = []
        
        for pt in remaining:
            d = distance(seed, pt)
            if d <= cluster_radius:
                cluster_pts.append(pt)
            else:
                new_remaining.append(pt)
        
        remaining = new_remaining
        
        # Calculate center
        cx = sum(p[0] for p in cluster_pts) / len(cluster_pts)
        cy = sum(p[1] for p in cluster_pts) / len(cluster_pts)
        cz = sum(p[2] for p in cluster_pts) / len(cluster_pts)
        
        clusters.append({
            'center': (cx, cy, cz),
            'point_count': len(cluster_pts),
            'radius': max(distance(seed, pt) for pt in cluster_pts) if len(cluster_pts) > 1 else 0
        })
    
    return clusters

def scan_for_ice(grid, position):
    """Scan for ice deposits at current position."""
    od = grid.get_first_device(OreDetectorDevice)
    if not od:
        return None, []
    
    od.enable()
    time.sleep(0.5)
    
    # Ore-only scan
    radar = RadarController(od, ore_only=True, radius=ORE_SCAN_RADIUS, cell_size=10)
    solid, meta, contacts, ore_cells = radar.scan_voxels()
    
    if not ore_cells:
        return None, []
    
    # Look for ice
    ice_cells = []
    other_cells = []
    for cell in ore_cells:
        ore_type = cell.get('ore') or cell.get('material') or ''
        if 'ice' in ore_type.lower():
            ice_cells.append(cell)
        else:
            other_cells.append(cell)
    
    return ice_cells, other_cells

def check_container_fullness(grid):
    containers = grid.find_devices_by_type(ContainerDevice)
    if not containers:
        return 0.0
    
    c = containers[0]
    t = c.telemetry or {}
    inv = t.get('inventory') or {}
    current = inv.get('currentVolume', 0)
    maximum = inv.get('maxVolume', 1)
    
    return current / maximum if maximum > 0 else 0.0

def undock(grid):
    connectors = grid.find_devices_by_type(ConnectorDevice)
    if not connectors:
        return True
    
    conn = connectors[0]
    t = conn.telemetry or {}
    if t.get('connectorStatus') == 'Connected':
        conn.disconnect()
        time.sleep(2)
    
    return True

def enable_systems(grid):
    rc = grid.get_first_device(RemoteControlDevice)
    if rc:
        rc.enable()
        time.sleep(0.3)
        rc.dampeners_on()
        time.sleep(0.3)
        rc.gyro_control_on()
        time.sleep(0.3)
        rc.thrusters_on()
        time.sleep(0.3)
    
    od = grid.get_first_device(OreDetectorDevice)
    if od:
        od.enable()
    
    return rc

def fly_to(grid, target_pos, speed=15):
    try:
        result = goto(grid, target_pos, speed=speed)
        return True
    except Exception as e:
        print(f"Fly error: {e}")
        return False

def start_mining(grid):
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        return False
    
    drill = drills[0]
    drill.enable()
    time.sleep(0.5)
    
    try:
        drill.start_drilling()
    except:
        pass
    
    return True

def stop_mining(grid):
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        return
    drills[0].disable()

def find_nearest_asteroid(grid, current_pos, asteroids):
    """Find nearest asteroid from list."""
    if not asteroids:
        return None
    
    nearest = None
    min_dist = float('inf')
    
    for ast in asteroids:
        pos = ast['center'] if isinstance(ast, dict) else ast
        d = distance(current_pos, pos)
        if d < min_dist:
            min_dist = d
            nearest = ast
    
    return nearest

def main():
    """Main mining loop - one iteration."""
    state = get_state()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] State: {state}")
    
    if state == 'idle':
        clear_visited()
        set_state('undocking')
        print("Starting mining cycle...")
        return
    
    elif state == 'undocking':
        grid = get_grid()
        undock(grid)
        enable_systems(grid)
        set_state('scanning')
        print("Undocked. Starting scan...")
        return
    
    elif state == 'scanning':
        grid = get_grid()
        pos = get_position(grid)
        
        print(f"Scanning for asteroids at ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})...")
        
        # 1. Scan for asteroids (solid points), filter visited
        asteroids = scan_for_asteroids(grid)
        unvisited = [a for a in asteroids if not is_visited(a['center'])]
        
        if unvisited:
            print(f"Found {len(unvisited)} unvisited asteroids (of {len(asteroids)} total)")
            nearest = find_nearest_asteroid(grid, pos, unvisited)
            if nearest:
                target = nearest['center']
                set_target(*target)
                set_state('flying_to_asteroid')
                print(f"Nearest asteroid at ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
                return
        
        # 2. No unvisited asteroids in range - try known locations
        print("No unvisited asteroids in range. Checking known locations...")
        known = load_known_asteroids()
        known_unvisited = [a for a in known if not is_visited(a['center'])]
        
        if known_unvisited:
            nearest = find_nearest_asteroid(grid, pos, known_unvisited)
            if nearest:
                target = nearest['center']
                set_target(*target)
                set_state('flying_to_asteroid')
                print(f"Flying to known {nearest['ore_type']} deposit at ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
                return
        
        # 3. No known locations - fly in a direction and scan
        print("No known locations. Flying to search area...")
        
        # Choose direction (away from base)
        base = prepare_grid(BASE_ID)
        time.sleep(0.5)
        base_pos = base.metadata.get('pos')
        
        # Direction from base
        dx = pos[0] - base_pos[0]
        dy = pos[1] - base_pos[1]
        dz = pos[2] - base_pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        
        if dist > 0:
            # Normalize and fly 2000m
            factor = 2000.0 / dist
            target = (pos[0] + dx*factor, pos[1] + dy*factor, pos[2] + dz*factor)
        else:
            # Default direction
            target = (pos[0], pos[1] + 2000, pos[2])
        
        set_target(*target)
        set_state('searching')
        print(f"Searching in direction ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        return
    
    elif state == 'flying_to_asteroid':
        grid = get_grid()
        target = get_target()
        pos = get_position(grid)
        
        if not target:
            set_state('scanning')
            return
        
        dist = distance(pos, target)
        
        if dist > 100:
            fly_to(grid, target, speed=15)
            print(f"Flying to asteroid: {dist:.0f}m remaining")
            return
        
        # Arrived at asteroid - scan for ice
        print("Arrived at asteroid. Scanning for ice...")
        ice_cells, other_cells = scan_for_ice(grid, pos)
        
        if ice_cells:
            # Found ice!
            ice_pos = ice_cells[0].get('position', target)
            set_target(*ice_pos)
            set_state('mining')
            print(f"Found ice at ({ice_pos[0]:.0f}, {ice_pos[1]:.0f}, {ice_pos[2]:.0f})")
            return
        
        # No ice - mark as visited and go back to scanning
        add_visited(target)
        print("No ice found here. Marked as visited. Rescanning...")
        set_state('scanning')
        return
    
    elif state == 'searching':
        grid = get_grid()
        target = get_target()
        pos = get_position(grid)
        
        if not target:
            set_state('scanning')
            return
        
        dist = distance(pos, target)
        
        if dist > 100:
            fly_to(grid, target, speed=15)
            print(f"Flying to search area: {dist:.0f}m remaining")
            return
        
        # Arrived at search area - scan
        print("Arrived at search area. Scanning...")
        
        # Scan for asteroids
        asteroids = scan_for_asteroids(grid)
        
        if asteroids:
            nearest = find_nearest_asteroid(grid, pos, asteroids)
            if nearest:
                target = nearest['center']
                set_target(*target)
                set_state('flying_to_asteroid')
                print(f"Found asteroid at ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
                return
        
        # No asteroids - try next direction
        print("No asteroids here. Trying next direction...")
        set_state('scanning')
        return
    
    elif state == 'mining':
        grid = get_grid()
        target = get_target()
        pos = get_position(grid)
        
        if not target:
            set_state('returning')
            return
        
        # Check container fullness
        fullness = check_container_fullness(grid)
        if fullness >= CONTAINER_FULL_THRESHOLD:
            stop_mining(grid)
            set_state('returning')
            print(f"Container {fullness*100:.0f}% full. Returning to base.")
            return
        
        # Check if close to ice
        dist = distance(pos, target)
        
        if dist > MINE_DISTANCE:
            fly_to(grid, target, speed=5)
            print(f"Flying to ice: {dist:.0f}m remaining")
            return
        
        # Start mining
        drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
        if drills and not drills[0].telemetry.get('enabled'):
            start_mining(grid)
            print("Started mining ice...")
        
        print(f"Mining... Container {fullness*100:.0f}% full")
        return
    
    elif state == 'returning':
        grid = get_grid()
        pos = get_position(grid)
        
        # Fly to base
        base = prepare_grid(BASE_ID)
        time.sleep(0.5)
        base_pos = base.metadata.get('pos')
        base_target = (base_pos[0], base_pos[1], base_pos[2])
        
        dist = distance(pos, base_target)
        
        if dist > 200:
            fly_to(grid, base_target, speed=15)
            print(f"Returning to base: {dist:.0f}m remaining")
            return
        
        # Near base - dock
        set_state('docking')
        print("Near base. Starting docking...")
        return
    
    elif state == 'docking':
        import subprocess
        result = subprocess.run([
            '/app/venv/bin/python',
            '/home/hermeswebui/se-data/scripts/docking/dock.py',
            SHIP_ID, BASE_ID, '100'
        ], capture_output=True, text=True, timeout=300)
        
        if 'DOCKING COMPLETE' in result.stdout:
            set_state('idle')
            print("Docked successfully. Mining cycle complete.")
        else:
            print(f"Docking failed: {result.stdout[-200:]}")
        
        return

if __name__ == '__main__':
    main()
