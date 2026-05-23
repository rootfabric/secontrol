import time
from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.common import close

grid = Grid.from_name("skynet-baza0")
drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]

# Full reset per docs
print("Full reset...")
drill.stop_drilling()
drill.turn_off()
time.sleep(0.5)

drill.set_script_controlled(True)
drill.set_collect_filter(["Ore"])
drill.set_ore_filters(["Nickel"], work_mode="Collect")
drill.set_work_mode("Collect")
drill.set_script_controlled(False)
drill.turn_on()

print("Monitoring for 60s...")
for i in range(20):
    time.sleep(3)
    drill.update()
    tel = drill.telemetry or {}
    targets = tel.get("drill_possible_targets", [])
    props = tel.get("properties", {})
    print(f"[{i*3}s] targets={len(targets)}, current={props.get('Drill.CurrentDrillTarget')}")

close(grid)