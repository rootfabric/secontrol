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

# Full reset
drill.stop_drilling()
time.sleep(0.5)
drill.send_command({"cmd": "set", "payload": {"property": "OnOff", "value": False}})
time.sleep(1)
drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})
time.sleep(0.3)
drill.set_property("AreaOffsetUpDown", 0.0)
drill.set_property("AreaOffsetFrontBack", 0.0)
drill.set_property("AreaOffsetLeftRight", 0.0)
time.sleep(0.3)
drill.send_command({"cmd": "set", "payload": {"property": "ScriptControlled", "value": False}})
time.sleep(0.3)
drill.send_command({"cmd": "set", "payload": {"property": "UseConveyor", "value": True}})
time.sleep(0.2)
drill.turn_on()
time.sleep(0.5)
drill.start_drilling()
time.sleep(5)

drill.update()
tel = drill.telemetry or {}
props = tel.get('properties', {})

print('=== Drill Properties ===')
print(f'OnOff: {props.get("OnOff")}')
print(f'Drill.WorkMode: {props.get("Drill.WorkMode")}')
print(f'Drill.ScriptControlled: {props.get("Drill.ScriptControlled")}')
print(f'UseConveyor: {props.get("UseConveyor")}')
print(f'AreaOffset: U={props.get("Drill.AreaOffsetUpDown")}, F={props.get("Drill.AreaOffsetFrontBack")}, L={props.get("Drill.AreaOffsetLeftRight")}')
print(f'Drill.AreaDepth: {props.get("Drill.AreaDepth")}')
print(f'Drill.AreaHeight: {props.get("Drill.AreaHeight")}')
print(f'Drill.AreaWidth: {props.get("Drill.AreaWidth")}')

# Check all drill-related telemetry keys
print('\n=== All keys containing "Drill" ===')
for k, v in sorted(props.items()):
    if 'Drill' in k:
        print(f'  {k}: {v}')

print('\n=== All keys in telemetry ===')
for k, v in sorted(tel.items()):
    if k != 'properties':
        print(f'  {k}: {v}')

# Check cargo
print('\n--- Cargo inventory ---')
cargo.update()
for inv in cargo.inventories():
    for item in (inv.items or []):
        print(f'  {item.display_name}: {item.amount:.1f}')

grid.close()