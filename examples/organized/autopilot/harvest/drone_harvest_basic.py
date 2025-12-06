#!/usr/bin/env python3
"""
Простой пример harvest-дрона с нано буром.

Бур бурит на месте и добывает ресурсы.
"""

from __future__ import annotations

import time
from typing import Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

# Настройки
GRID_NAME = "taburet2"  # Имя грида дрона
DRILL_DURATION_SECONDS = 5.0  # Время бурения в секундах
ORE_TYPE = "Uranium"  # Тип добываемой руды


def find_devices(grid) -> tuple[Optional[NanobotDrillSystemDevice], Optional[ContainerDevice]]:
    """Найти необходимые устройства на гриде."""
    drill = None
    container = None

    print(f"Поиск устройств на гриде {grid.name} (ID: {grid.grid_id})")
    print(f"Найдено устройств: {len(grid.devices)}")

    for device in grid.devices.values():
        # print(f"  Устройство: {device.name or 'unnamed'} (ID: {device.device_id}, тип: {getattr(device, 'device_type', 'unknown')})")
        if device.device_type == "ship_drill":
            drill = device
        elif isinstance(device, ContainerDevice):
            # Берем первый найденный контейнер
            if container is None:
                container = device

    return drill, container


def main() -> None:
    print("Запуск harvest-дрона (бурение на месте)...")

    # Подготовка грида
    grid = prepare_grid(GRID_NAME)
    try:
        # Поиск устройств
        drill, container = find_devices(grid)

        if not drill:
            print("Ошибка: Nanobot Drill System не найден на гриде!")
            return
        if not container:
            print("Ошибка: Контейнер дрона не найден на гриде!")
            return

        drill.update()

        print(f"Найдены устройства:")
        print(f"  Drill: {drill.name or drill.device_id}")
        print(f"  Container: {container.name or container.device_id}")

        # Настройка бура
        print(f"Настраиваем бур на добычу: {ORE_TYPE}")
        if hasattr(drill, 'set_ore_filters'):
            drill.set_ore_filters([ORE_TYPE])
        if hasattr(drill, 'set_script_controlled'):
            drill.set_script_controlled(True)

        # Проверяем статус бура
        if hasattr(drill, 'status_summary'):
            status = drill.status_summary()
            print(f"Статус бура: {status}")

        print("Начинаем бурение на месте...")
        if hasattr(drill, 'turn_on'):
            drill.turn_on()
        if hasattr(drill, 'start_drilling'):
            drill.start_drilling()

        # Ждем окончания бурения
        print(f"Бурим {DRILL_DURATION_SECONDS} секунд...")
        time.sleep(DRILL_DURATION_SECONDS)

        print("Останавливаем бурение...")
        if hasattr(drill, 'stop_drilling'):
            drill.stop_drilling()
        if hasattr(drill, 'turn_off'):
            drill.turn_off()

        # Собираем ресурсы из бура в контейнер дрона
        print("Собираем ресурсы...")
        drill_items = drill.items()
        if drill_items:
            print(f"Найдено ресурсов: {len(drill_items)} тип(ов)")
            for item in drill_items:
                print(f"  - {item.get('type', 'unknown')}: {item.get('amount', 0)}")
            drill.move_all(container)
            print("Ресурсы перенесены в контейнер дрона")
        else:
            print("Ресурсы не найдены в буре")

        print("Harvest завершен!")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
