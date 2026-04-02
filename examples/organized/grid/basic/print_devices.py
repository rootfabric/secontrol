from secontrol.common import prepare_grid, close
from secontrol.redis_client import RedisEventClient

try:
    grid = prepare_grid()  # Восстановить на prepare_grid()

    print(f"Grid: {grid.name} (id={grid.grid_id})")
    print(f"Total devices: {len(grid.devices)}")

    for device in grid.devices.values():
        print(f" - {device.device_id}: {device.name} ({device.device_type})")

    close(grid)
except Exception as e:
    print(f"Error: {e}")
