from __future__ import annotations

import datetime
import time

from secontrol.base_device import Grid
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

    # Set initial number (like in working code)
    num = 0
    display.set_text(str(num))
    display.send_command({"cmd": "update"})
    time.sleep(0.1)  # Wait for update

    # Prime telemetry with continuous activity (like in working code)
    print("Priming telemetry...")
    while True:  # Infinite loop like in working code
        display.set_text(str(num))
        # display.send_command({"cmd": "update"})  # Commented like in working code
        num += 1
        time.sleep(0.01)
        current = display.get_text()
        print(current)
        if num > 10:  # Exit after some iterations
            break
    print("Priming complete")

    # Keep telemetry active with continuous loop (like in working code)
    print("Keeping telemetry active...")
    num = 0
    while True:  # Infinite loop like in working code
        display.set_text(str(num))
        # display.send_command({"cmd": "update"})
        num += 1
        time.sleep(0.01)
        print(display.get_text())
        if num > 50:  # Exit after more iterations
            break
    print("Telemetry active, starting benchmark")

    print("Starting benchmark: send number -> wait for confirmation -> measure confirmed ops/sec")
    print("Press Ctrl+C to stop")

    local_num = 0
    start_time = time.time()
    operations = 0

    try:
        while True:
            # Increment counter
            local_num += 1

            # Send number to display
            display.set_text(str(local_num))
            display.send_command({"cmd": "update"})

            # Wait for telemetry to confirm the new value
            timeout = time.time() + 5.0  # 5 second timeout per operation
            while time.time() < timeout:
                current_text = display.get_text()
                if current_text == str(local_num):
                    # Success - telemetry confirmed the update
                    operations += 1
                    break
                time.sleep(0.001)  # Small polling delay
            else:
                # Timeout - couldn't confirm this update
                print(f"Timeout waiting for confirmation of {local_num}")
                break

            # Print stats every second
            elapsed = time.time() - start_time
            if elapsed >= 1.0:
                rate = operations / elapsed
                print(f"{datetime.datetime.now()} | Confirmed ops/sec: {rate:.2f} | Last num: {local_num}")
                start_time = time.time()
                operations = 0

    except KeyboardInterrupt:
        print("\nBenchmark stopped")


def main() -> None:
    grid = prepare_grid()
    benchmark_display(grid)


if __name__ == "__main__":
    main()
