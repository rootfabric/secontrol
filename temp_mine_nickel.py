import time
from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.common import close

grid = Grid.from_name("skynet-baza0")
drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]

# Ship pos (drill pos)
ship_pos = [-50663.449, 146566.486, -137681.556]
# Nickel_1 center
nickel_pos = [-50626.3, 146646.9, -137739.8]

# Direction from ship to Nickel
dx = nickel_pos[0] - ship_pos[0]  # +37.1 (right)
dy = nickel_pos[1] - ship_pos[1]   # +80.4 (up)
dz = nickel_pos[2] - ship_pos[2]   # -58.4 (back)

print(f"Direction to Nickel: dx={dx:.1f}, dy={dy:.1f}, dz={dz:.1f}")
dist = (dx**2 + dy**2 + dz**2)**0.5
print(f"Distance: {dist:.1f}m")

# Stop drill first
drill.stop_drilling()
drill.turn_off()
time.sleep(0.5)

# Setup Nickel filter
drill.set_script_controlled(True)
drill.set_collect_filter(["Ore"])
drill.set_ore_filters(["Nickel"], work_mode="Collect")
drill.set_work_mode("Collect")
drill.set_script_controlled(False)
drill.turn_on()
time.sleep(0.5)

# Try area offset — maximum 5 steps in each direction
# Based on direction: dx>0 (right), dy>0 (up), dz<0 (back)
print()
print("Setting AreaOffset max toward Nickel...")
for _ in range(5):
    drill.increase_area_offset_left_right()
    time.sleep(0.1)
for _ in range(5):
    drill.increase_area_offset_up_down()
    time.sleep(0.1)
for _ in range(5):
    drill.decrease_area_offset_front_back()
    time.sleep(0.1)

time.sleep(1)
drill.update()
print(f"Targets after offset: {len(drill.telemetry.get('drill_possible_targets', []))}")
print(f"CurrentTarget: {drill.telemetry.get('properties', {}).get('Drill.CurrentDrillTarget')}")

close(grid)