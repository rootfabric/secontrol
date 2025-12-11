from __future__ import annotations

import time

from secontrol import Grid
from secontrol.devices.display_device import DisplayDevice
from secontrol.common import prepare_grid


def benchmark_display(grid: Grid) -> None:
    grid_id = grid.grid_id
    grid_name = grid.name or 'unnamed'
    print(f"Starting benchmark for grid {grid_id} ({grid_name})")

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

    try:
        while True:
            num += 1
            display.set_text(str(num))
            # time.sleep(0.10)
            # display.send_command({"cmd": "update"})

            while True:

                # для фосажа
                display.set_text(str(num))
                display.send_command({"cmd": "update"})

                n = display.get_text()

                # print(int(n) , num)
                if int(n) == num:
                    match_count += 1

                    # Calculate and print rate every 2 matches
                    if match_count % 2 == 0:
                        elapsed = time.time() - start_time
                        rate = match_count / elapsed
                        print(f"Match rate: {rate:.2f} matches per second")
                    break
                time.sleep(0.1)




    except KeyboardInterrupt:
        print("\nBenchmark stopped")



def main() -> None:
    grid = prepare_grid("139498645541187359")
    benchmark_display(grid)


if __name__ == "__main__":
    main()
