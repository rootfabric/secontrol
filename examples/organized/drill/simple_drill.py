"""Basic lamp control example using :class:`LampDevice`."""

from __future__ import annotations

import time

from secontrol.common import close, prepare_grid, resolve_owner_id
from secontrol.devices.ship_drill_device import ShipDrillDevice


def main() -> None:

    grid = prepare_grid("Owl")

    # Найти первый коннектор на гриде
    drills = list(grid.find_devices_by_type(ShipDrillDevice))
    if not drills:
        print("No drills found on the grid")
        return

    drill: ShipDrillDevice = drills[0]

    print(f"Found {len(drills)} lamps: {[l.name for l in drills]}")

    drill.set_enabled(True)

    time.sleep(5)

    drill.set_enabled(False)


if __name__ == "__main__":
    main()
