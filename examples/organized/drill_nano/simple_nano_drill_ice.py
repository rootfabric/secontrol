from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

grid = Grid.from_name("taburet2")
drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]

drill.turn_off()
drill.set_script_controlled(True)
drill.set_collect_filter(["Ore"])
drill.set_ore_filters(["Ice"], work_mode="Collect")
drill.set_work_mode("Collect")
drill.set_script_controlled(False)
drill.set_work_mode("Collect")
drill.turn_on()

print("work mode:", drill.get_work_mode())
print("ores:", drill.debug_get_enabled_known_ores())