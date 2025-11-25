from __future__ import annotations

import time
from secontrol.common import close, prepare_grid

from secontrol.tools.navigation_tools import goto



if __name__ == "__main__":
    # Вставьте GPS коннектора базы:
    FIXED_GPS = "GPS:Target:1083872.23:145818.45:1661756.98:"
    FIXED_GPS = "GPS:Target:1083890.90:145781.56:1661724.25:"

    grid = prepare_grid("taburet")

    goto(
        ship_grid=grid,
        point_target=FIXED_GPS
    )
