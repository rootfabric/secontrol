import time
from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.common import close

grid = Grid.from_name("skynet-baza0")
drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]

# Reset without ore filter - just see if ANY targets appear
drill.stop_drilling()
drill.turn_off()
time.sleep(0.5)

drill.set_script_controlled(True)
drill.set_collect_filter(["Ore"])
drill.set_work_mode("Collect")
drill.set_script_controlled(False)
drill.turn_on()

time.sleep(2)
drill.update()

print("=== Wide sweep without ore filter ===")

best_offset = None
best_count = 0

# Wide sweep: FB -50 to +50, UD -50 to +50
for fb in range(-50, 55, 10):
    for ud in range(-50, 55, 10):
        drill.set_property("Drill.AreaOffsetFrontBack", float(fb))
        drill.set_property("Drill.AreaOffsetUpDown", float(ud))
        drill.set_property("Drill.AreaOffsetLeftRight", 0.0)
        time.sleep(0.3)
        drill.update()
        targets = drill.telemetry.get("drill_possibledrilltargets", [])
        if len(targets) > best_count:
            best_count = len(targets)
            best_offset = (fb, ud)
            print(f"  BEST: FB={fb}, UD={ud} -> {len(targets)} targets")

print()
if best_offset:
    print(f"Best: FrontBack={best_offset[0]}, UpDown={best_offset[1]}, targets={best_count}")
else:
    print("No targets found at any offset.")

close(grid)