from __future__ import annotations

from typing import List, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.lamp_device import LampDevice


class App:
    def __init__(self):
        self.counter: int = 0
        # self._grid, self._owns_grid = _resolve_grid(grid, grid_id)
        self._lamps: List[LampDevice] = []
        self._on: bool = False

        # Пытаемся получить grid_id независимо от конкретного класса грида
        self.grid_id = None

    def start(self):
        # Сообщение как в воркере
        if self.grid_id is None:
            self.grid_id = grid.grid_id

        self._grid = prepare_grid(self.grid_id )

        # Находим лампы: сперва по типу, затем через isinstance
        lamps: List[LampDevice] = []
        try:
            # если у грида есть метод поиска по типу
            lamps = list(self._grid.find_devices_by_type("lamp"))  # type: ignore[attr-defined]
        except Exception:
            pass

        if not lamps:
            try:
                devices = getattr(self._grid, "devices", {})  # dict[id, device]
                lamps = [d for d in devices.values() if isinstance(d, LampDevice)]
            except Exception:
                lamps = []

        self._lamps = lamps
        print(f"Lamps found: {len(self._lamps)}")

    def step(self):
        self.counter += 1
        self._on = not self._on

        # Переключаем все лампы; ошибки каждого устройства не валят цикл
        for lamp in self._lamps:
            try:
                lamp.set_enabled(self._on)
            except Exception:
                pass

        state = "ON" if self._on else "OFF"
        if self.grid_id is not None:
            print(f"Step {self.counter} on grid {self.grid_id}: lamps -> {state}")
        else:
            print(f"Step {self.counter}: lamps -> {state}")



if __name__ == "__main__":
    # Локальный запуск для отладки
    import time
    app = App()  # или App(grid_id="..."), или App(grid=уже_существующий_грид)


    app.grid_id = prepare_grid().grid_id

    app.start()
    for _ in range(6):
        app.step()
        time.sleep(1)
    app.close()
