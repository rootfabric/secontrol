#!/usr/bin/env python3
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(WORKSPACE, '.env'))

from secontrol.common import prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

grid = prepare_grid('skynet-baza0')
drill = grid.get_first_device(NanobotDrillSystemDevice)

drill.update()
print('=== All properties ===')
props = drill.telemetry.get('properties', {})
for k, v in sorted(props.items()):
    print(f'  {k}: {v}')

grid.close()