"""Update telemetry example - Force refresh telemetry for devices on the grid."""

from __future__ import annotations

import time

from secontrol.base_device import BaseDevice
from secontrol.common import close, prepare_grid, resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grid = prepare_grid()

    try:
        devices = [device for device in grid.devices.values() if isinstance(device, BaseDevice)]
        if not devices:
            print("No devices detected on the selected grid.")
            return

        print(f"Found {len(devices)} devices on grid '{grid.name}'")
        for i, device in enumerate(devices[:5]):  # Limit to first 5 for brevity
            print(f"  {i+1}. Device {device.device_id}: {device.name!r} ({device.device_type})")

        print("\nSending 'update' command to all devices to force telemetry refresh...")

        updated_count = 0
        for device in devices:
            try:
                # Send the update command (equivalent to "update", "refresh", "telemetry" in the C# plugin)
                sent = device.send_command({"cmd": "update"})
                if sent > 0:
                    updated_count += 1
                    print(f"Sent update command to device {device.device_id} ({device.name!r})")
                else:
                    print(f"Failed to send update command to device {device.device_id}")
            except Exception as e:
                print(f"Error updating device {device.device_id}: {e}")

        print(f"\nSuccessfully sent update commands to {updated_count} out of {len(devices)} devices")

        # Wait a moment for telemetry to refresh
        print("Waiting 2 seconds for telemetry to refresh...")
        time.sleep(2.0)

        # Show updated telemetry for first device as example
        if devices:
            first_device = devices[0]
            print(f"\nExample updated telemetry for device {first_device.device_id}:")
            print(f"Name: {first_device.name}")
            print(f"Enabled: {first_device.is_enabled()}")
            if first_device.telemetry:
                # Print some key fields
                telemetry = first_device.telemetry
                for key in ["load", "timestamp", "ownerId"]:
                    if key in telemetry:
                        print(f"{key}: {telemetry[key]}")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
