from secontrol.common import prepare_grid
import sys, time

GRID = "skynet-farpost0"
# NAME = "Батарея 111"
NAME = "Батарея 44"

grid = prepare_grid(GRID)
time.sleep(1.5)

dev = next((d for d in grid.devices.values()
            if d.device_type == "battery" and d.name == NAME), None)
if dev is None:
    print(f"not found: {NAME}"); sys.exit(1)

t = dev.telemetry or {}
print(f"id={dev.device_id}  name={dev.name!r}  "
      f"chargeMode={t.get('chargeMode')}  semiAuto={t.get('semiAuto')}  "
      f"enabled={dev.is_enabled()}  maxOut={t.get('maxOutputMW')}MW")

print("set_mode('auto') ->", dev.set_mode("auto"))
time.sleep(1.0)
print("enable()         ->", dev.enable())
time.sleep(2.0)

t = dev.telemetry or {}
print(f"after:  chargeMode={t.get('chargeMode')}  semiAuto={t.get('semiAuto')}  "
      f"enabled={dev.is_enabled()}  maxOut={t.get('maxOutputMW')}MW  "
      f"in={t.get('currentInputMW')}MW  out={t.get('currentOutputMW')}MW")