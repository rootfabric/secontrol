#!/usr/bin/env python3
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(WORKSPACE, '.env'))

from secontrol.controllers.space_navigator_controller import SpaceNavigatorController
from secontrol.tools.navigation_tools import get_world_position

asteroid_center = (-50531.7, 146631.4, -137826.2)

controller = SpaceNavigatorController(
    grid_name='skynet-baza0',
    target_is_obstacle=True,
)

try:
    controller.rc.update()
    pos = get_world_position(controller.rc)
    print(f'Start: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})')
    d = math.sqrt(sum((a-b)**2 for a,b in zip(pos, asteroid_center)))
    print(f'Target: {asteroid_center}, distance: {d:.1f}m')
    print(f'Ship radius: {controller.ship_radius:.1f}m')

    result = controller.navigate_to(asteroid_center)
    print(f'\nStatus: {result.status}')
    print(f'Final: {result.final_position}')
    if result.final_position:
        d = math.sqrt(sum((a-b)**2 for a,b in zip(result.final_position, asteroid_center)))
        print(f'Distance to asteroid center: {d:.1f}m')
finally:
    controller.close()