"""Фильтрация руды и запуск Nanobot Drill System на короткий цикл."""

from __future__ import annotations

import time
from typing import Iterable

from secontrol.common import close, prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

PREFERRED_ORES: tuple[str, ...] = (
    "Uranium",
    "Iron",
    "Nickel",
    "Cobalt",
)
DRILL_DURATION_SECONDS = 6.0


def pick_target_ore(drill: NanobotDrillSystemDevice, priorities: Iterable[str]) -> str:
    """Выбрать руду из телеметрии устройства согласно приоритетам."""

    available = drill.known_ore_targets()
    if available:
        for ore in priorities:
            if ore in available:
                return ore
        return available[0]

    # Если телеметрия не даёт вариантов, используем первый приоритет
    for ore in priorities:
        if ore:
            return ore
    raise RuntimeError("Не задан список приоритетов руд")


def find_drill(grid) -> NanobotDrillSystemDevice | None:
    for device in grid.devices.values():
        if isinstance(device, NanobotDrillSystemDevice):
            return device
    return None


def main() -> None:
    grid = prepare_grid()
    try:
        drill = find_drill(grid)
        if drill is None:
            print("На гриде нет Nanobot Drill System.")
            return

        status = drill.status_summary()
        print(f"Используем {drill.name or drill.device_id} — статус: {status.get('type', 'unknown')}")
        print(
            "Нагрузка обновления: window=",
            drill.load_window(),
            ", avgMs=",
            drill.load_update_metrics().get("avgMs"),
            sep="",
        )

        target = pick_target_ore(drill, PREFERRED_ORES)
        print(f"Выбранная руда по фильтру: {target}")
        drill.set_ore_filters([target])

        print("Включаем систему и запускаем бурение...")
        drill.turn_on()
        drill.start_drilling()
        print(f"Добываем {target} в течение {DRILL_DURATION_SECONDS:.1f} секунд")
        time.sleep(DRILL_DURATION_SECONDS)

        print("Останавливаем бурение и отключаем блок")
        drill.stop_drilling()
        drill.turn_off()
    finally:
        close(grid)


if __name__ == "__main__":
    main()
