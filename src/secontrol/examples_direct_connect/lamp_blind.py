"""Basic lamp control example using :class:`LampDevice`."""

from __future__ import annotations

import time

from secontrol.common import close, prepare_grid, resolve_owner_id
from secontrol.devices.lamp_device import LampDevice


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grid = prepare_grid()
    print(grid.name)
    print(grid.is_subgrid)

    # lamp = next((device for device in grid.devices.values() if isinstance(device, LampDevice)), None)
    # if lamp is None:
    #     print("No lamp detected on the selected grid.")
    #     return
    #
    # print(f"Found lamp {lamp.device_id} named {lamp.name!r}")
    # print("Initial telemetry:", lamp.telemetry)
    #
    # lamp.set_enabled(True)
    # print("Lamp enabled.")
    #
    # for red, green, blue in ((1.0, 0.2, 0.2), (0.2, 1.0, 0.2), (0.2, 0.4, 1.0)):
    #     lamp.set_color(rgb=(red, green, blue))
    #     print(f"Set color to {(red, green, blue)}; telemetry color={lamp.color_rgb()}")
    #     time.sleep(1.0)
    #
    # lamp.set_enabled(False)
    # print("Lamp disabled.")

    # Собираем все лампы грида
    lamps = [d for d in grid.devices.values() if isinstance(d, LampDevice)]
    if not lamps:
        print("No lamps detected on the selected grid.")
        return

    print(f"Found {len(lamps)} lamps: {[l.name for l in lamps]}")

    while 1:
        # Включаем все лампы
        for lamp in lamps:
            lamp.set_enabled(True)
        print("All lamps enabled.")

        time.sleep(1)

        for lamp in lamps:
            lamp.set_enabled(False)

        time.sleep(1)
    # # Цвета для моргания
    # colors = [
    #     (1.0, 0.2, 0.2),  # красный
    #     (0.2, 1.0, 0.2),  # зелёный
    #     (0.2, 0.4, 1.0),  # синий
    # ]
    #
    # # Моргаем всеми лампами синхронно
    # for red, green, blue in colors:
    #     for lamp in lamps:
    #         lamp.set_color(rgb=(red, green, blue))
    #     print(f"Set color to {(red, green, blue)}")
    #     time.sleep(1.0)
    #
    # # Выключаем все лампы
    # for lamp in lamps:
    #     lamp.set_enabled(False)
    # print("All lamps disabled.")
    #

if __name__ == "__main__":
    main()
