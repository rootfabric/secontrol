"""Basic lamp control example using :class:`LampDevice`."""

from __future__ import annotations

import time

from secontrol.common import close, prepare_grid, resolve_owner_id
from secontrol.devices.ship_drill_device import ShipDrillDevice


def main() -> None:
    grid = prepare_grid("DroneBase")

    # Найти первый коннектор на гриде
    drill: ShipDrillDevice = grid.get_first_device(ShipDrillDevice)
    if not drill:
        print("No drills found on the grid")
        return

    drill.set_enabled(True)

    time.sleep(5)

    drill.set_enabled(False)


if __name__ == "__main__":
    main()
