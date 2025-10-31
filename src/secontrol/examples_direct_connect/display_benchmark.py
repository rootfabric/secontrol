from __future__ import annotations

import datetime
import threading
import time
from typing import Dict, Tuple, Any, List, Set, Optional

from secontrol.base_device import Grid
from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, resolve_player_id, _is_subgrid
from secontrol.redis_client import RedisEventClient


def benchmark_display(client: RedisEventClient, owner_id: str, player_id: str, grid_info: Dict[str, Any]) -> None:
    grid_id = str(grid_info.get('id'))
    grid_name = grid_info.get('name', 'unnamed')
    print(f"Starting benchmark for grid {grid_id} ({grid_name})")

    grid = Grid(client, owner_id, grid_id, player_id)

    displays = list(grid.find_devices_by_type(DisplayDevice))
    print(f"Found {len(displays)} display device(s) on grid {grid_name}:")

    if not displays:
        print(f"No displays found on grid {grid_name}, skipping.")
        return

    # Use the first display
    display = displays[0]
    print(f"Using display: {display.name or 'Display'} (ID: {display.device_id})")

    # Set display to text mode
    display.set_mode("text")
    time.sleep(0.1)  # Wait for mode change

    # Set initial number
    num = 0
    display.set_text(str(num))
    display.send_command({"cmd": "update"})
    time.sleep(0.1)  # Wait for update

    local_num = 0

    start_time = time.time()
    operations = 0

    try:
        while True:
            # Increment local counter
            local_num += 1

            # Set new number
            display.set_text(str(local_num))
            time.sleep(0.1)  # Small delay
            display.send_command({"cmd": "update"})

            # Wait for telemetry to reflect the new number
            timeout = time.time() + 20.0  # 2 second timeout
            while time.time() < timeout:
                display.refresh_telemetry()
                current_text = display.get_text()
                print(current_text)
                if current_text == str(local_num):
                    break
                time.sleep(0.01)  # Small delay
            else:
                print(f"Timeout waiting for telemetry update to {local_num}")
                break

            operations += 1

            # Print rate per second
            elapsed = time.time() - start_time
            if elapsed >= 1.0:
                rate = operations / elapsed
                print(f"{datetime.datetime.now()} Benchmark: {rate:.2f} increments/sec, last num: {local_num}")
                start_time = time.time()
                operations = 0

    except KeyboardInterrupt:
        pass


def main() -> None:
    owner_id = resolve_owner_id()
    player_id = resolve_player_id(owner_id)
    print(f"Owner ID: {owner_id}")

    client = RedisEventClient()

    try:
        grids = client.list_grids(owner_id)
        if not grids:
            print("No grids found.")
            return

        # Filter non-subgrids
        non_subgrids = [g for g in grids if not _is_subgrid(g)]
        print(f"Found {len(non_subgrids)} main grids.")

        for grid_info in non_subgrids:
            benchmark_display(client, owner_id, player_id, grid_info)
            # Only do one grid, break after first
            break

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
