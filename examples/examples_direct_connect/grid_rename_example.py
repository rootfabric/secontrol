"""Rename grid example - Change the display name of a grid."""

from __future__ import annotations

import time

from secontrol.common import close, prepare_grid, resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grid = prepare_grid()

    try:
        print(f"Current grid name: '{grid.name}' (ID: {grid.grid_id})")

        # Example new name - in practice you'd get this from user input
        new_name = "My Renamed Grid"

        print(f"Renaming grid to: '{new_name}'")

        # Send the rename command (equivalent to "rename", "set_name", "name" in the C# plugin)
        sent = grid.rename(new_name)
        if sent > 0:
            print(f"Successfully sent rename command (published to {sent} channels)")
        else:
            print("Failed to send rename command")
            return

        # Wait a moment for the change to propagate
        print("Waiting 2 seconds for rename to take effect...")
        time.sleep(2.0)

        # Verify the name change by checking the updated grid name
        # The grid name should automatically update via the gridinfo subscription
        print(f"Updated grid name: '{grid.name}'")

        # Optionally, you could also check the raw gridinfo payload
        if hasattr(grid, 'metadata') and grid.metadata:
            metadata_name = None
            for key in ('name', 'gridName', 'displayName'):
                if grid.metadata.get(key):
                    metadata_name = grid.metadata[key]
                    break
            if metadata_name:
                print(f"Metadata name: '{metadata_name}'")

        print("\nTo test different names, modify the 'new_name' variable in the script.")
        print("In a real application, you'd prompt the user for the desired name.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
