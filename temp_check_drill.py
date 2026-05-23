#!/usr/bin/env python3
import sys, os, time, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(WORKSPACE, '.env'))

from secontrol.common import prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.tools.navigation_tools import get_world_position

grid = prepare_grid('skynet-baza0')

drill = grid.get_first_device(NanobotDrillSystemDevice)
cargo = grid.get_first_device(ContainerDevice)
radar = grid.get_first_device(OreDetectorDevice)

# Get RC position
from secontrol.devices.remote_control_device import RemoteControlDevice
rc = grid.get_first_device(RemoteControlDevice)
rc.update()
ship_pos = get_world_position(rc)

nickel = (-50627.7, 146647.9, -137740.7)
asteroid_center = (-50531.7, 146631.4, -137826.2)

print(f'Ship position: {ship_pos}')
print(f'Ship to Nickel: {math.sqrt(sum((a-b)**2 for a,b in zip(ship_pos, nickel))):.1f}m')
print(f'Ship to asteroid center: {math.sqrt(sum((a-b)**2 for a,b in zip(ship_pos, asteroid_center))):.1f}m')

# Check asteroidIndex
radar.update()
tel = radar.telemetry or {}
ai = tel.get('asteroidIndex', {})
for item in ai.get('items', []):
    if '180762343' in str(item.get('name', '')):
        print(f'\nAsteroid: {item.get("name")}')
        print(f'  distance: {item.get("distance")}')
        print(f'  surfaceDistance: {item.get("surfaceDistance")}')

print(f'\nDrill WorkMode: {drill.telemetry.get("properties", {}).get("Drill.WorkMode")}')
print(f'Drill ScriptControlled: {drill.telemetry.get("properties", {}).get("ScriptControlled")}')

grid.close()