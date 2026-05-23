#!/usr/bin/env python3
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(WORKSPACE, '.env'))

from secontrol.common import prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.container_device import ContainerDevice

grid = prepare_grid('skynet-baza0')
drill = grid.get_first_device(NanobotDrillSystemDevice)
cargo = grid.get_first_device(ContainerDevice)

# Configure drill
drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})
time.sleep(0.3)
drill.send_command({"cmd": "set", "payload": {"property": "ScriptControlled", "value": False}})
time.sleep(0.3)
drill.send_command({"cmd": "set", "payload": {"property": "UseConveyor", "value": True}})
time.sleep(0.2)
drill.turn_on()
time.sleep(0.5)
drill.start_drilling()

print('Drill started. Waiting 30 seconds...')
time.sleep(30)

drill.update()
props = drill.telemetry.get('properties', {})
targets = props.get('Drill.PossibleDrillTargets', [])
current = props.get('Drill.CurrentDrillTarget')
print(f'\nPossible targets: {len(targets)}')
print(f'Current target: {current}')
for t in targets[:10]:
    print(f'  {t}')

print('\n--- Cargo inventory ---')
cargo.update()
for inv in cargo.inventories():
    for item in (inv.items or []):
        print(f'  {item.display_name}: {item.amount:.1f}')

grid.close()