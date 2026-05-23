#!/usr/bin/env python3
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(WORKSPACE, '.env'))

from secontrol.controllers.space_navigator_controller import (
    SpaceNavigatorController,
    FINE_SCAN,
    ScanProfile,
)

nickel_target = (-50627.7, 146647.9, -137740.7)

# Custom fine scan with larger radius, less clearance
fine = ScanProfile(
    name="FINE",
    radius=500.0,
    cell_size=5.0,
    rescan_distance=200.0,
    clearance_voxels=5,  # much less clearance = can get closer to voxels
)

print('=== Flying to Nickel with tight clearance ===')
controller = SpaceNavigatorController(
    grid_name='skynet-baza0',
    target_is_obstacle=False,
    max_replans=100,
    max_steps=500,
    fine_scan=fine,
)

try:
    controller.rc.update()
    from secontrol.tools.navigation_tools import get_world_position
    pos = get_world_position(controller.rc)
    print(f'Start: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})')
    d = math.sqrt(sum((a-b)**2 for a,b in zip(pos, nickel_target)))
    print(f'Target: {nickel_target}, distance: {d:.1f}m')
    print(f'Ship radius: {controller.ship_radius:.1f}m')

    result = controller.navigate_to(nickel_target)
    print(f'\nStatus: {result.status}')
    print(f'Final: {result.final_position}')
    if result.final_position:
        d = math.sqrt(sum((a-b)**2 for a,b in zip(result.final_position, nickel_target)))
        print(f'Distance to Nickel: {d:.1f}m')
    print(f'Profile: {result.profile}, Scans: {result.scan_count}, Replans: {result.replans}')
finally:
    controller.close()

# Check drill targets
from secontrol.common import prepare_grid
grid = prepare_grid('skynet-baza0')
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
drill = grid.get_first_device(NanobotDrillSystemDevice)
drill.update()
props = drill.telemetry.get('properties', {})
targets = props.get('Drill.PossibleDrillTargets', [])
current = props.get('Drill.CurrentDrillTarget')
print(f'\n=== After flight ===')
print(f'Possible targets: {len(targets)}')
print(f'Current target: {current}')
for t in targets[:10]:
    print(f'  {t}')
grid.close()