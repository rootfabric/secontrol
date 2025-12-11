from __future__ import annotations

import datetime
import time
from typing import List, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.lamp_device import LampDevice
from secontrol import Grid

import secontrol


class App:
    def __init__(self, grid_id):
        self.grid = prepare_grid(grid_id)

        self.counter: int = 0
        # self._grid, self._owns_grid = _resolve_grid(grid, grid_id)
        self.lamps: List[LampDevice] = []
        self._on: bool = False
        print(f"[worker] secontrol version: {secontrol.__version__}", flush=True)

    def start(self):

        lamps = list(self.grid.find_devices_by_type(LampDevice))

        self.lamps = lamps
        print(f"Lamps found: {len(self.lamps)}")

    def step(self):
        self.counter += 1
        self._on = not self._on

        # Переключаем все лампы; 
        for lamp in self.lamps:
            lamp.set_enabled(self._on)

        print(f"{datetime.datetime.now()} Step {self.counter} on grid {self.grid.grid_id}: lamps -> {self._on}")


if __name__ == "__main__":
    # Локальный запуск для отладки

    grid = prepare_grid("Rover")
    app = App(grid)

    app.start()
    while True:
        app.step()
        time.sleep(1)
