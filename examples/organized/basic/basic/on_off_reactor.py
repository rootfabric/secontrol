from secontrol.common import prepare_grid
import sys, time

GRID = "skynet-farpost0"

grid = prepare_grid(GRID)
time.sleep(1.5)

reactors = [d for d in grid.devices.values() if d.device_type == "reactor"]
if not reactors:
    print("no reactors found"); sys.exit(1)

print(f"found {len(reactors)} reactor(s)")
for dev in reactors:
    inv = (dev.inventories() or [None])[0]
    fuel = ""
    if inv and inv.items:
        fuel = "  fuel: " + ", ".join(f"{i.display_name}={i.amount}" for i in inv.items)
    fs = dev.functional_status()
    print(f"  id={dev.device_id} name={dev.name!r}  "
          f"enabled={dev.is_enabled()}  working={fs['isWorking']}  "
          f"output={dev.current_output():.3f}/{dev.max_output():.3f}MW  "
          f"useConveyor={dev.use_conveyor()}{fuel}")

cmd = sys.argv[1] if len(sys.argv) > 1 else "on"
for dev in reactors:
    if cmd == "on":
        res = dev.set_enabled(True)
    elif cmd == "off":
        res = dev.set_enabled(False)
    elif cmd == "toggle":
        res = dev.toggle_enabled()
    elif cmd == "conveyor_on":
        res = dev.set_use_conveyor(True)
    elif cmd == "conveyor_off":
        res = dev.set_use_conveyor(False)
    else:
        print(f"usage: {sys.argv[0]} [on|off|toggle|conveyor_on|conveyor_off]"); sys.exit(2)
    print(f"  {cmd} -> {dev.name!r} id={dev.device_id}: {res}")