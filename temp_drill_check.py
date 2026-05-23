#!/usr/bin/env python3
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(WORKSPACE, '.env'))

from secontrol.common import prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.tools.navigation_tools import get_world_position

grid = prepare_grid('skynet-baza0')
drill = grid.get_first_device(NanobotDrillSystemDevice)
cargo = grid.get_first_device(ContainerDevice)

# Check current state
drill.update()
tel = drill.telemetry or {}
props = tel.get('properties', {})
print(f'Drill WorkMode: {props.get("Drill.WorkMode")}')
print(f'Drill ScriptControlled: {props.get("Drill.ScriptControlled")}')
print(f'OnOff: {props.get("OnOff")}')
print(f'UseConveyor: {props.get("UseConveyor")}')
print(f'AreaOffset: U={props.get("Drill.AreaOffsetUpDown")}, F={props.get("Drill.AreaOffsetFrontBack")}, L={props.get("Drill.AreaOffsetLeftRight")}')

targets = props.get('Drill.PossibleDrillTargets', [])
current = props.get('Drill.CurrentDrillTarget')
print(f'\nPossible targets: {len(targets)}')
print(f'Current target: {current}')

# Check cargo
print('\n--- Cargo inventory ---')
cargo.update()
for inv in cargo.inventories():
    for item in (inv.items or []):
        print(f'  {item.display_name}: {item.amount:.1f}')

grid.close()