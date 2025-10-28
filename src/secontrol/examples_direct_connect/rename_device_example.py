"""Rename device example - Change the custom name of a device (equivalent to C# plugin rename command)."""

from __future__ import annotations

import time

from secontrol.base_device import BaseDevice
from secontrol.common import close, prepare_grid, resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grid = prepare_grid()

    try:
        # Find a device to rename - prefer containers or text panels for testing
        devices = [device for device in grid.devices.values() if isinstance(device, BaseDevice)]
        if not devices:
            print("No devices detected on the selected grid.")
            return

        # Select first device for demonstration
        device = devices[0]

        print(f"Found {len(devices)} devices on grid '{grid.name}'")
        print(f"Selected device {device.device_id}: '{device.name}' ({device.device_type})")

        # Example new name - in practice you'd get this from user input
        new_name = "Renamed Device Example"

        print(f"Renaming device {device.device_id} to: '{new_name}'")

        # Send the rename command (equivalent to "rename", "set_name", "name" in the C# plugin)
        sent = device.send_command({
            "cmd": "set_name",
            "name": new_name
        })

        if sent > 0:
            print(f"Successfully sent rename command (published to {sent} channels)")
        else:
            print("Failed to send rename command")
            return

        # The name change will automatically update in telemetry when the device responds
        # In the C# plugin, this sets Block.CustomName and immediately publishes updated telemetry
        print("Waiting 2 seconds for rename to take effect and telemetry to update...")

        # Wait for the change to propagate
        time.sleep(2.0)

        # Check if name was updated
        old_name = device.name
        print(f"Device name before: '{old_name}'")
        print(f"Device name after: '{device.name}'")

        if device.name != old_name:
            print("✓ Name successfully updated!")
        else:
            print("⚠ Name may not have been updated yet - check telemetry or try again.")

        # Show current telemetry as example
        if device.telemetry:
            telemetry_name = device.telemetry.get("name") or device.telemetry.get("customName")
            print(f"Telemetry name field: '{telemetry_name}'")

        print("\nTo test different names, modify the 'new_name' variable in the script.")
        print("In a real application, you'd prompt the user for the desired device name.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
