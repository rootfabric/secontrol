from __future__ import annotations

import datetime
from typing import List, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.lamp_device import LampDevice


class App:
    def __init__(self):
        self.grid_id = None

        self.counter: int = 0
        # self._grid, self._owns_grid = _resolve_grid(grid, grid_id)
        self.lamps: List[LampDevice] = []
        self._on: bool = False



    def start(self):
        # Сообщение как в воркере
        if self.grid_id is None:
            self.grid_id = grid.grid_id

        self.grid = prepare_grid(self.grid_id)

         # если у грида есть метод поиска по типу
        lamps = list(self.grid.find_devices_by_type("lamp"))  # type: ignore[attr-defined]

        self.lamps = lamps
        print(f"Lamps found: {len(self.lamps)}")

    def step(self):
        self.counter += 1
        self._on = not self._on

        # Переключаем все лампы; ошибки каждого устройства не валят цикл
        for lamp in self.lamps:
            lamp.set_enabled(self._on)

        print(f"{datetime.datetime.now()} Step {self.counter} on grid {self.grid_id}: lamps -> {self._on}")


if __name__ == "__main__":
    # Локальный запуск для отладки
    import time

    app = App()  # или App(grid_id="..."), или App(grid=уже_существующий_грид)

    app.grid_id = prepare_grid().grid_id

    app.start()
    for _ in range(60):
        app.step()
        time.sleep(1)

