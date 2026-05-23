import time
from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.common import close

grid = Grid.from_name("skynet-baza0")

# Проверяем surfaceDistance в asteroid index
radar = grid.get_first_device(OreDetectorDevice)
radar.update()
tel = radar.telemetry or {}
ai = tel.get("asteroidIndex", {})
print(f"Asteroid index ready: {ai.get('ready')}")
print(f"Asteroid count: {ai.get('count')}")

# Ищем наш астероид
ship_pos = [-50663.44893962817, 146566.48574301042, -137681.55585947016]
for ast in ai.get("items", []):
    if "180762343" in str(ast.get("seed", "")):
        print(f"  Our asteroid: {ast.get('name')}")
        print(f"  distance: {ast.get('distance')}m")
        print(f"  surfaceDistance: {ast.get('surfaceDistance')}m")

# Проверяем drill telemetry для drill targets
drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]
drill.update()
tel = drill.telemetry or {}
props = tel.get("properties", {})
print()
print(f"Drill ScriptControlled: {props.get('ScriptControlled')}")
print(f"Drill CurrentDrillTarget: {props.get('Drill.CurrentDrillTarget')}")
print(f"Drill possible targets: {tel.get('drill_possible_drill_targets', [])}")
print(f"Drill drill_possible_targets: {tel.get('drill_possible_targets', [])}")

close(grid)