from __future__ import annotations

import threading
import time
from typing import Dict, Tuple, Any, List, Set, Optional

from secontrol.base_device import Grid
from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, resolve_player_id, _is_subgrid
from secontrol.redis_client import RedisEventClient


def benchmark_display(display: DisplayDevice) -> None:
    print(f"Benchmarking display: {display.name or 'Display'} (ID: {display.device_id})")

    # Set initial number
    local_num = 0
    display.set_text(str(local_num))
    # display.send_command({"cmd": "update"})
    time.sleep(0.1)  # Wait for update

    start_time = time.time()
    operations = 0

    try:
        while True:
            # Increment local counter
            local_num += 1

            # Set new number
            display.set_text(str(local_num))
            # display.send_command({"cmd": "update"})
            # time.sleep(0.01)  # Small delay

            operations += 1

            # Print rate per second
            elapsed = time.time() - start_time
            if elapsed >= 1.0:
                rate = operations / elapsed
                print(f"Benchmark for {display.name or 'Display'} (ID: {display.device_id}): {rate:.2f} ops/sec")
                start_time = time.time()
                operations = 0

    except KeyboardInterrupt:
        pass


def benchmark_for_grid(grid: Grid) -> None:
    displays = list(grid.find_devices_by_type(DisplayDevice))
    print(f"Found {len(displays)} display device(s) on grid {grid.name}:")

    if not displays:
        print(f"No displays found on grid {grid.name}, skipping.")
        return

    # Set all displays to text mode at startup
    for display in displays:
        print(f"Setting {display.name or 'Display'} (ID: {display.device_id}) to text mode.")
        display.set_mode("text")
    time.sleep(0.1)  # Wait for mode changes to take effect

    threads = []
    for display in displays:
        t = threading.Thread(target=benchmark_display, args=(display,))
        threads.append(t)
        t.start()
        # break

    # Wait for all threads
    for t in threads:
        t.join()


def main() -> None:
    owner_id = resolve_owner_id()
    player_id = resolve_player_id(owner_id)
    print(f"Owner ID: {owner_id}")

    try:
        client = RedisEventClient()

        grids = client.list_grids(owner_id)
        if not grids:
            print("No grids found.")
            return

        # Filter non-subgrids
        non_subgrids = [g for g in grids if not _is_subgrid(g)]
        print(f"Found {len(non_subgrids)} main grids.")

        for grid_info in non_subgrids:
            grid = Grid(client, owner_id, str(grid_info['id']), player_id, grid_info.get('name'))
            benchmark_for_grid(grid)
            break  # Only one grid

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
