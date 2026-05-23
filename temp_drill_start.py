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

print('Drill:', drill.name if drill else None)
print('Cargo:', cargo.name if cargo else None)

if drill:
    print('\n--- Configure drill ---')
    drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})
    time.sleep(0.3)
    drill.set_property("ScriptControlled", False)
    time.sleep(0.3)
    drill.set_use_conveyor(True)
    time.sleep(0.3)
    drill.turn_on()
    time.sleep(0.5)
    drill.start_drilling()
    time.sleep(3)

    print('\n--- Drill telemetry ---')
    drill.update()
    tel = drill.telemetry or {}
    props = tel.get('properties', {})
    targets = tel.get('drill_possibleDrilltargets', [])
    current = props.get('Drill.CurrentDrillTarget')
    print(f'Possible targets: {len(targets)}')
    print(f'Current target: {current}')
    print(f'Targets: {targets[:10]}')

    print('\n--- Cargo inventory ---')
    if cargo:
        cargo.update()
        for inv in cargo.inventories():
            for item in (inv.items or []):
                print(f'  {item.display_name}: {item.amount:.1f}')

grid.close()