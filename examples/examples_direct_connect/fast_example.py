from secontrol.common import prepare_grid

grid = prepare_grid()
print(", ".join((d.name or f"{d.device_type}:{d.device_id}") for d in grid.devices.values()) or "(no devices)")


