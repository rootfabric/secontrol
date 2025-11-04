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
    # time.sleep(0.1)  # Wait for update

    # Initialize benchmark variables
    start_time = time.time()
    match_count = 0

    # while 1:
    #     num += 1
    #     display.set_text(str(num))
    #     # display.send_command({"cmd": "update"})
    #     time.sleep(0.1)
    #     print(display.get_text())

    while 1:
        num += 1
        # display.set_text(num)
        display.set_text(str(num))
        while 1:


            # time.sleep(0.1)
            n = display.get_text()
            # print(n, num)
            if int(n) == num:
                match_count += 1
                # Calculate and print rate every 10 matches
                if match_count % 2 == 0:
                    elapsed = time.time() - start_time
                    rate = match_count / elapsed
                    print(f"Match rate: {rate:.2f} matches per second")
                break



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
